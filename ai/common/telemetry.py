"""
Negelir — Intent telemetry sink.
Per Gemini §4 Phase 3: persistent observability for TQU classifications
and QID intent distributions, backed by Redis streams.

Falls back to no-op if Redis is unavailable (non-blocking).

Phase 10 §10.14 Prometheus metrics:
  - nlp_pipeline_latency_seconds{stage, intent} histogram
  - nlp_intent_confidence{intent} summary
  - nlp_humanizer_breaker_state{state} gauge
  - nlp_proofreader_block_total{reason} counter
  - nlp_lexicon_version{file} info gauge

Phase 10 §10.14 W3C tracing:
  - Trace propagation via traceparent (Phase 9 §9.5)
  - Per-stage spans: normalize, intent, entities, dispatch, predict_wait,
    render, humanize, proofread
"""

import json
import time
from contextlib import contextmanager
from typing import Any

from common.config import Config
from common.logger import get_logger

try:
    from prometheus_client import Counter, Gauge, Histogram, Info, Summary
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

log = get_logger("telemetry")


# ── Phase 10 §10.14 Prometheus metrics ──────────────────────────────────
# Cardinality bounded by intent enum + degraded flag (no per-team labels).
# Aligned with §9.17.5 bucket discipline.

if _PROMETHEUS_AVAILABLE:
    # nlp_pipeline_latency_seconds{stage, intent} — histogram
    # Stages: normalize, intent, entities, dispatch, predict_wait, render, humanize, proofread
    NLP_PIPELINE_LATENCY = Histogram(
        "nlp_pipeline_latency_seconds",
        "NLP pipeline stage latency",
        labelnames=["stage", "intent"],
        buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
    )

    # nlp_intent_confidence{intent} — summary (p50/p95/p99)
    NLP_INTENT_CONFIDENCE = Summary(
        "nlp_intent_confidence",
        "Intent classifier confidence distribution",
        labelnames=["intent"],
    )

    # nlp_humanizer_breaker_state{state} — gauge
    # States: closed, open, half_open
    NLP_HUMANIZER_BREAKER_STATE = Gauge(
        "nlp_humanizer_breaker_state",
        "Humanizer circuit breaker state",
        labelnames=["state"],
    )

    # nlp_proofreader_block_total{reason} — counter
    NLP_PROOFREADER_BLOCK_TOTAL = Counter(
        "nlp_proofreader_block_total",
        "Proofreader block events by reason",
        labelnames=["reason"],
    )

    # nlp_input_repair_total{repair_class} — counter of input repair events per class
    NLP_INPUT_REPAIR_TOTAL = Counter(
        "nlp_input_repair_total",
        "NLP input repair events by class",
        labelnames=["repair_class"],
    )

    # nlp_input_repair_density — histogram of repairs/token-count per query
    NLP_INPUT_REPAIR_DENSITY = Histogram(
        "nlp_input_repair_density",
        "NLP input repair density per query",
        buckets=(0.001, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0),
    )

    # nlp_dialect_normalization_rate{dialect_class} — histogram of dialect normalization observations per class
    NLP_DIALECT_NORMALIZATION_RATE = Histogram(
        "nlp_dialect_normalization_rate",
        "NLP dialect normalization observations by class",
        labelnames=["dialect_class"],
        buckets=(1.0,),
    )

    # nlp_disambiguation_offered_total{cause} — counter of disambiguation offers
    NLP_DISAMBIGUATION_OFFERED_TOTAL = Counter(
        "nlp_disambiguation_offered_total",
        "Disambiguation offers by cause",
        labelnames=["cause"],
    )

    # nlp_offensive_input_total{offense_class} — counter of offensive input tokens
    NLP_OFFENSIVE_INPUT_TOTAL = Counter(
        "nlp_offensive_input_total",
        "Offensive input tokens by class",
        labelnames=["offense_class"],
    )

    # nlp_humanizer_tokens_emitted_total{tenant_class, intent} — counter of humanizer tokens emitted
    NLP_HUMANIZER_TOKENS_EMITTED_TOTAL = Counter(
        "nlp_humanizer_tokens_emitted_total",
        "Humanizer tokens emitted by tenant class and intent",
        labelnames=["tenant_class", "intent"],
    )

    # nlp_politeness_class_distribution{politeness_class} — histogram of politeness class observations
    NLP_POLITENESS_CLASS_DISTRIBUTION = Histogram(
        "nlp_politeness_class_distribution",
        "Distribution of politeness classes observed in NLP inputs",
        labelnames=["politeness_class"],
        buckets=(1.0,),
    )

    # nlp_lexicon_version{file} — info gauge
    NLP_LEXICON_VERSION = Info(
        "nlp_lexicon_version",
        "Loaded lexicon version metadata",
    )
else:
    NLP_PIPELINE_LATENCY = None
    NLP_INTENT_CONFIDENCE = None
    NLP_HUMANIZER_BREAKER_STATE = None
    NLP_PROOFREADER_BLOCK_TOTAL = None
    NLP_HUMANIZER_TOKENS_EMITTED_TOTAL = None
    NLP_LEXICON_VERSION = None


class TelemetrySink:
    """
    Async-safe telemetry writer.  Uses Redis XADD (streams) so entries
    are durable and support consumer-group replay for dashboards later.

    Streams created:
      negelir:tqu:classifications  — every classify() call
      negelir:qid:snapshots        — periodic QID distribution snapshots
    """

    _CLASSIFICATION_STREAM = "negelir:tqu:classifications"
    _QID_STREAM = "negelir:qid:snapshots"
    _DEFAULT_MAX_STREAM_LEN = 50_000  # auto-trim oldest entries

    def __init__(self, config: Config | None = None):
        self._redis = None
        cfg = config or Config()
        self._max_stream_len = getattr(cfg, "telemetry_max_stream_len", self._DEFAULT_MAX_STREAM_LEN)
        try:
            import redis
            self._redis = redis.Redis(
                host=cfg.redis_host,
                port=cfg.redis_port,
                decode_responses=True,
                socket_connect_timeout=getattr(cfg, "redis_socket_timeout", 2),
            )
            self._redis.ping()
            log.info("Telemetry sink connected to Redis %s:%s", cfg.redis_host, cfg.redis_port)
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis unavailable (%s) — telemetry disabled", exc)
            self._redis = None

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    # ── TQU classification events ────────────────────────

    def log_classification(
        self,
        raw_input: str,
        intent_id: str | None,
        confidence: float,
        success: bool,
    ) -> None:
        """Push one classification event to the stream."""
        if not self._redis:
            return
        entry: dict[str, Any] = {
            "ts": str(time.time()),
            "intent": intent_id or "none",
            "conf": str(round(confidence, 4)),
            "ok": str(int(success)),
            "input_len": str(len(raw_input)),
        }
        try:
            self._redis.xadd(
                self._CLASSIFICATION_STREAM,
                entry,
                maxlen=self._max_stream_len,
            )
        except Exception:  # noqa: BLE001
            pass  # non-blocking

    # ── NLP structured logs (Phase 10 §10.14) ────────────

    def log_nlp_request(
        self,
        qa_correlation_id: str,
        request_id: str,
        intent: str,
        intent_confidence: float,
        entity_count: int,
        humanizer_used: bool,
        proofreader_status: str,
    ) -> None:
        """
        Log a structured NLP request event.
        Per Phase 10 §10.14: carries envelope + intent metadata, NEVER raw/sanitized text (PII discipline).
        """
        # Defensive: refuse to log if any param looks like user input text
        # (guards against accidental PII leakage via param transposition)
        if len(str(qa_correlation_id)) > 64 or len(str(request_id)) > 64:
            log.warning("Refusing nlp_request log: ID field suspiciously long (PII guard)")
            return

        entry: dict[str, str] = {
            "ts": str(time.time()),
            "qa_correlation_id": qa_correlation_id,
            "request_id": request_id,
            "intent": intent,
            "intent_confidence": f"{intent_confidence:.4f}",
            "entity_count": str(entity_count),
            "humanizer_used": str(int(humanizer_used)),
            "proofreader_status": proofreader_status,
        }
        # Also emit as structured log line (mirrors §9.8 audit discipline)
        log.info(
            "NLP request processed",
            extra={
                "structured": True,
                **entry,
            },
        )

        # Record Prometheus metric: intent confidence
        if _PROMETHEUS_AVAILABLE and NLP_INTENT_CONFIDENCE:
            try:
                NLP_INTENT_CONFIDENCE.labels(intent=intent).observe(intent_confidence)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    # ── W3C tracing (Phase 10 §10.14) ────────────────────

    @contextmanager
    def nlp_span(
        self,
        trace_id: str,
        stage: str,
        intent: str = "unknown",
    ):
        """
        Context manager for recording per-stage NLP pipeline spans.
        Follows W3C trace propagation from Phase 9 §9.5.

        Stages (per §10.14): normalize, intent, entities, dispatch,
        predict_wait, render, humanize, proofread.

        Args:
            trace_id: W3C traceparent trace_id from envelope (Phase 9 §9.5)
            stage: NLP pipeline stage name
            intent: Intent classification (when known; defaults to "unknown")

        Usage:
            with telemetry.nlp_span(trace_id, "normalize", intent):
                # ... do work ...
        """
        start = time.monotonic()
        try:
            yield
        finally:
            latency_s = time.monotonic() - start
            # Record Prometheus histogram
            if _PROMETHEUS_AVAILABLE and NLP_PIPELINE_LATENCY:
                try:
                    NLP_PIPELINE_LATENCY.labels(stage=stage, intent=intent).observe(latency_s)
                except Exception:  # noqa: BLE001
                    pass  # non-blocking

            # Structured log the span
            log.debug(
                f"NLP span: {stage}",
                extra={
                    "structured": True,
                    "trace_id": trace_id,
                    "stage": stage,
                    "intent": intent,
                    "latency_s": f"{latency_s:.6f}",
                },
            )

    # ── QID snapshots ────────────────────────────────────

    def log_qid_snapshot(self, match_id: str, volume: int, distribution: dict[str, float]) -> None:
        """Push a QID distribution snapshot for one match."""
        if not self._redis:
            return
        entry: dict[str, str] = {
            "ts": str(time.time()),
            "match_id": match_id,
            "volume": str(volume),
            "dist": json.dumps(distribution),
        }
        try:
            self._redis.xadd(
                self._QID_STREAM,
                entry,
                maxlen=self._max_stream_len,
            )
        except Exception:  # noqa: BLE001
            pass

    # ── QID persistence (full dump / restore) ────────────

    def persist_qid_profiles(self, profiles: dict) -> int:
        """Persist full QID profiles dict to Redis hash for crash recovery.
        Returns count of matches persisted."""
        if not self._redis:
            return 0
        key = "negelir:qid:profiles"
        count = 0
        try:
            pipe = self._redis.pipeline()
            for match_id, profile_data in profiles.items():
                pipe.hset(key, match_id, json.dumps(profile_data))
                count += 1
            pipe.execute()
            log.debug("Persisted %d QID profiles to Redis", count)
        except Exception:  # noqa: BLE001
            count = 0
        return count

    def restore_qid_profiles(self) -> dict:
        """Restore QID profiles from Redis hash. Returns dict of match_id → profile_data."""
        if not self._redis:
            return {}
        key = "negelir:qid:profiles"
        try:
            raw = self._redis.hgetall(key)
            return {k: json.loads(v) for k, v in raw.items()}
        except Exception:  # noqa: BLE001
            return {}

    # ── Stats ────────────────────────────────────────────

    def stream_lengths(self) -> dict[str, int]:
        """Return current stream lengths for monitoring."""
        if not self._redis:
            return {}
        try:
            return {
                "classifications": self._redis.xlen(self._CLASSIFICATION_STREAM),
                "qid_snapshots": self._redis.xlen(self._QID_STREAM),
            }
        except Exception:  # noqa: BLE001
            return {}


    # ── Phase 10 §10.14 Prometheus metric helpers ────────────────

    def record_pipeline_stage_latency(self, stage: str, intent: str, latency_seconds: float) -> None:
        """
        Record latency for an NLP pipeline stage.
        stage ∈ {normalize, intent, entities, dispatch, predict_wait, render, humanize, proofread}
        """
        if _PROMETHEUS_AVAILABLE and NLP_PIPELINE_LATENCY:
            try:
                NLP_PIPELINE_LATENCY.labels(stage=stage, intent=intent).observe(latency_seconds)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_proofreader_block(self, reason: str) -> None:
        """
        Increment proofreader block counter.
        reason ∈ {citation_drift, mid_sentence_english, length_under, length_over,
                  pii_redacted, forbidden_phrase, suffix_harmony}
        """
        if _PROMETHEUS_AVAILABLE and NLP_PROOFREADER_BLOCK_TOTAL:
            try:
                NLP_PROOFREADER_BLOCK_TOTAL.labels(reason=reason).inc()
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
        """
        Increment an NLP input repair event counter for the given repair class.
        """
        if count <= 0:
            return
        if _PROMETHEUS_AVAILABLE and NLP_INPUT_REPAIR_TOTAL:
            try:
                NLP_INPUT_REPAIR_TOTAL.labels(repair_class=repair_class).inc(count)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
        """
        Record the ratio of repair events to token count for a single query.
        """
        if token_count <= 0:
            return
        ratio = repairs / float(token_count)
        if _PROMETHEUS_AVAILABLE and NLP_INPUT_REPAIR_DENSITY:
            try:
                NLP_INPUT_REPAIR_DENSITY.observe(ratio)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_dialect_normalization(self, dialect_class: str, count: int = 1) -> None:
        """
        Record a regional dialect normalization observation by dialect class.
        """
        if count <= 0:
            return
        if _PROMETHEUS_AVAILABLE and NLP_DIALECT_NORMALIZATION_RATE:
            try:
                NLP_DIALECT_NORMALIZATION_RATE.labels(dialect_class=dialect_class).observe(float(count))
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_disambiguation_offered(self, cause: str) -> None:
        """
        Increment a disambiguation-offer counter by cause.
        cause ∈ {low_intent_conf, ambiguous_entity, ambiguous_match_pair, confused_phonetic_alias}
        """
        if _PROMETHEUS_AVAILABLE and NLP_DISAMBIGUATION_OFFERED_TOTAL:
            try:
                NLP_DISAMBIGUATION_OFFERED_TOTAL.labels(cause=cause).inc()
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_offensive_input(self, offense_class: str, count: int = 1) -> None:
        """
        Increment an offensive-input counter for the given class.
        offense_class ∈ {mild, slur, severe_threat}
        """
        if count <= 0:
            return
        if _PROMETHEUS_AVAILABLE and NLP_OFFENSIVE_INPUT_TOTAL:
            try:
                NLP_OFFENSIVE_INPUT_TOTAL.labels(offense_class=offense_class).inc(count)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_humanizer_tokens_emitted(
        self,
        tenant_class: str,
        intent: str,
        count: int = 1,
    ) -> None:
        """
        Record the number of humanizer tokens emitted for the given tenant class and intent.

        Args:
            tenant_class: One of the closed-set tenant classes from cfg.nlp_tenant_class_enum.
            intent: Closed-set NLP intent identifier.
            count: Number of tokens emitted. Must be > 0.
        """
        if count <= 0:
            return
        if _PROMETHEUS_AVAILABLE and NLP_HUMANIZER_TOKENS_EMITTED_TOTAL:
            try:
                NLP_HUMANIZER_TOKENS_EMITTED_TOTAL.labels(
                    tenant_class=tenant_class,
                    intent=intent,
                ).inc(count)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def record_nlp_politeness_class(self, politeness_class: str) -> None:
        """
        Record the observed politeness class for an NLP input.
        """
        if _PROMETHEUS_AVAILABLE and NLP_POLITENESS_CLASS_DISTRIBUTION:
            try:
                NLP_POLITENESS_CLASS_DISTRIBUTION.labels(
                    politeness_class=politeness_class,
                ).observe(1.0)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def set_humanizer_breaker_state(self, state: str) -> None:
        """
        Set humanizer circuit breaker state gauge.
        state ∈ {closed, open, half_open}
        """
        if _PROMETHEUS_AVAILABLE and NLP_HUMANIZER_BREAKER_STATE:
            try:
                # Reset all states to 0, then set the current state to 1
                for s in ["closed", "open", "half_open"]:
                    NLP_HUMANIZER_BREAKER_STATE.labels(state=s).set(0)
                NLP_HUMANIZER_BREAKER_STATE.labels(state=state).set(1)
            except Exception:  # noqa: BLE001
                pass  # non-blocking

    def set_lexicon_version(self, file: str, version: str, generated_at_utc: str) -> None:
        """
        Record lexicon version info gauge.
        file ∈ {teams, players, leagues, competitions, markets, dialects}
        """
        if _PROMETHEUS_AVAILABLE and NLP_LEXICON_VERSION:
            try:
                NLP_LEXICON_VERSION.info({
                    "file": file,
                    "version": version,
                    "generated_at_utc": generated_at_utc,
                })
            except Exception:  # noqa: BLE001
                pass  # non-blocking


# Module-level singleton — lazy init on first import
_sink: TelemetrySink | None = None


def get_sink() -> TelemetrySink:
    global _sink
    if _sink is None:
        _sink = TelemetrySink()
    return _sink
