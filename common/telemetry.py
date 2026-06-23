"""
Negelir — Intent telemetry sink.
Per Gemini §4 Phase 3: persistent observability for TQU classifications
and QID intent distributions, backed by Redis streams.

Falls back to no-op if Redis is unavailable (non-blocking).

Phase 10 §10.14 Prometheus metrics:
  - common_pipeline_latency_seconds{stage, intent} histogram
  - common_intent_confidence_gauge{intent} summary
  - common_humanizer_breaker_state_gauge{state} gauge
  - common_proofreader_block_total{reason} counter
  - common_lexicon_version_gauge{file} info gauge

Phase 10 §10.14 W3C tracing:
  - Trace propagation via traceparent (Phase 9 §9.5)
  - Per-stage spans: normalize, intent, entities, dispatch, predict_wait,
    render, humanize, proofread
"""

import collections
import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Callable

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
    # common_pipeline_latency_seconds{stage, intent} — histogram
    # Stages: normalize, intent, entities, dispatch, predict_wait, render, humanize, proofread
    NLP_PIPELINE_LATENCY = Histogram(
        "common_pipeline_latency_seconds",
        "NLP pipeline stage latency",
        labelnames=["stage", "intent"],
        buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
    )

    # common_intent_confidence_gauge{intent} — summary (p50/p95/p99)
    NLP_INTENT_CONFIDENCE = Summary(
        "common_intent_confidence_gauge",
        "Intent classifier confidence distribution",
        labelnames=["intent"],
    )

    # common_humanizer_breaker_state_gauge{state} — gauge
    # States: closed, open, half_open
    NLP_HUMANIZER_BREAKER_STATE = Gauge(
        "common_humanizer_breaker_state_gauge",
        "Humanizer circuit breaker state",
        labelnames=["state"],
    )

    # common_proofreader_block_total{reason} — counter
    NLP_PROOFREADER_BLOCK_TOTAL = Counter(
        "common_proofreader_block_total",
        "Proofreader block events by reason",
        labelnames=["reason"],
    )

    # common_prober_success_rate_gauge{intent} — last outcome of synthetic prober requests
    NLP_PROBER_SUCCESS_RATE = Gauge(
        "common_prober_success_rate_gauge",
        "Synthetic prober success rate by intent",
        labelnames=["intent"],
    )

    # common_flame_capture_armed_count — gauge of currently armed flame captures
    NLP_FLAME_CAPTURE_ARMED_COUNT = Gauge(
        "common_flame_capture_armed_count",
        "Number of currently armed NLP flame capture requests",
    )

    # common_input_repair_total{repair_class} — counter of input repair events per class
    NLP_INPUT_REPAIR_TOTAL = Counter(
        "common_input_repair_total",
        "NLP input repair events by class",
        labelnames=["repair_class"],
    )

    # common_input_shout_total — counter of normalized shout input observations
    NLP_INPUT_SHOUT_TOTAL = Counter(
        "common_input_shout_total",
        "NLP shout input events",
    )

    # common_input_repair_density_gauge — histogram of repairs/token-count per query
    NLP_INPUT_REPAIR_DENSITY = Histogram(
        "common_input_repair_density_gauge",
        "NLP input repair density per query",
        buckets=(0.001, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0),
    )

    # common_empty_input_rate_per_subject_gauge{subject} — histogram of per-subject empty-input abuse rate
    NLP_EMPTY_INPUT_RATE_PER_SUBJECT = Histogram(
        "common_empty_input_rate_per_subject_gauge",
        "Per-subject empty-input rate for NLP abuse detection",
        labelnames=["subject"],
        buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0),
    )

    # common_lexicon_coverage_gauge{intent_class} — histogram of resolvable lexicon hit fraction per query
    NLP_LEXICON_COVERAGE = Histogram(
        "common_lexicon_coverage_gauge",
        "NLP lexicon coverage per intent class",
        labelnames=["intent_class"],
        buckets=(0.0, 0.25, 0.5, 0.75, 1.0),
    )

    # common_classifier_extractor_skew_gauge{intent} — histogram of classifier vs extractor skew per intent
    NLP_CLASSIFIER_EXTRACTOR_SKEW = Histogram(
        "common_classifier_extractor_skew_gauge",
        "Classifier-extractor skew per NLP intent",
        labelnames=["intent"],
        buckets=(0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0),
    )

    # common_dialect_normalization_rate_gauge{dialect_class} — histogram of dialect normalization observations per class
    NLP_DIALECT_NORMALIZATION_RATE = Histogram(
        "common_dialect_normalization_rate_gauge",
        "NLP dialect normalization observations by class",
        labelnames=["dialect_class"],
        buckets=(1.0,),
    )

    # common_eval_corpus_growth_rate_gauge{intent_class} — histogram of new eval corpus rows added per intent class
    NLP_EVAL_CORPUS_GROWTH_RATE = Histogram(
        "common_eval_corpus_growth_rate_gauge",
        "New NLP evaluation corpus rows added per intent class",
        labelnames=["intent_class"],
        buckets=(1.0, 5.0, 10.0, 25.0, 50.0, 100.0),
    )

    # common_disambiguation_offered_total{cause} — counter of disambiguation offers
    NLP_DISAMBIGUATION_OFFERED_TOTAL = Counter(
        "common_disambiguation_offered_total",
        "Disambiguation offers by cause",
        labelnames=["cause"],
    )

    # common_offensive_input_total{offense_class} — counter of offensive input tokens
    NLP_OFFENSIVE_INPUT_TOTAL = Counter(
        "common_offensive_input_total",
        "Offensive input tokens by class",
        labelnames=["offense_class"],
    )

    # common_sarcasm_cue_fire_rate_gauge{cue_id} — histogram of sarcasm cue observations
    NLP_SARCASM_CUE_FIRE_RATE = Histogram(
        "common_sarcasm_cue_fire_rate_gauge",
        "NLP sarcasm cue fire rate by cue id",
        labelnames=["cue_id"],
        buckets=(1.0,),
    )

    # common_humanizer_tokens_emitted_total{tenant_class, intent} — counter of humanizer tokens emitted
    NLP_HUMANIZER_TOKENS_EMITTED_TOTAL = Counter(
        "common_humanizer_tokens_emitted_total",
        "Humanizer tokens emitted by tenant class and intent",
        labelnames=["tenant_class", "intent"],
    )

    # common_politeness_class_distribution_gauge{politeness_class} — histogram of politeness class observations
    NLP_POLITENESS_CLASS_DISTRIBUTION = Histogram(
        "common_politeness_class_distribution_gauge",
        "Distribution of politeness classes observed in NLP inputs",
        labelnames=["politeness_class"],
        buckets=(1.0,),
    )

    # common_lexicon_version_gauge{file} — info gauge
    NLP_LEXICON_VERSION = Info(
        "common_lexicon_version_gauge",
        "Loaded lexicon version metadata",
    )

    # Phase 13.2 — fixture schema-gate metrics
    # common_fixture_competition_missing_total{league_id} — counter of fixtures missing required competition fields for T3 leagues
    FIXTURE_COMPETITION_MISSING_TOTAL = Counter(
        "common_fixture_competition_missing_total",
        "Fixtures with missing competition fields (T3 tier allowed with warning)",
        labelnames=["league_id"],
    )
else:
    NLP_PIPELINE_LATENCY = None
    NLP_INTENT_CONFIDENCE = None
    NLP_HUMANIZER_BREAKER_STATE = None
    NLP_PROOFREADER_BLOCK_TOTAL = None
    NLP_PROBER_SUCCESS_RATE = None
    NLP_INPUT_REPAIR_TOTAL = None
    NLP_INPUT_SHOUT_TOTAL = None
    NLP_INPUT_REPAIR_DENSITY = None
    NLP_EMPTY_INPUT_RATE_PER_SUBJECT = None
    NLP_HUMANIZER_TOKENS_EMITTED_TOTAL = None
    NLP_EVAL_CORPUS_GROWTH_RATE = None
    NLP_FLAME_CAPTURE_ARMED_COUNT = None
    NLP_LEXICON_VERSION = None
    NLP_CLASSIFIER_EXTRACTOR_SKEW = None
    NLP_LEXICON_COVERAGE = None
    NLP_DIALECT_NORMALIZATION_RATE = None
    NLP_DISAMBIGUATION_OFFERED_TOTAL = None
    NLP_OFFENSIVE_INPUT_TOTAL = None
    NLP_SARCASM_CUE_FIRE_RATE = None
    NLP_POLITENESS_CLASS_DISTRIBUTION = None
    FIXTURE_COMPETITION_MISSING_TOTAL = None


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

    def __init__(self, config: Config | None = None, clock: Callable[[], float] | None = None):
        self._redis = None
        self._redis_attempted_connection = False
        cfg = config or Config()
        self._redis_config = {
            "host": cfg.redis_host,
            "port": cfg.redis_port,
            "decode_responses": True,
            "socket_connect_timeout": getattr(cfg, "redis_socket_timeout", 2),
        }
        self._clock = clock or time.monotonic
        self._max_stream_len = getattr(cfg, "telemetry_max_stream_len", self._DEFAULT_MAX_STREAM_LEN)
        self._unresolved_token_counts: collections.Counter[str] = collections.Counter()
        self._unresolved_token_window_start: float = self._clock()
        self._unresolved_token_top_k = max(1, int(getattr(cfg, "nlp_unresolved_token_top_k", 50)))
        self._unresolved_token_window_s = max(1, int(getattr(cfg, "nlp_unresolved_token_rolling_window_s", 3600)))
        self._unresolved_token_max_unredacted_len = max(1, int(getattr(cfg, "nlp_log_max_unredacted_str_len", 64)))
        self._alert_callback: Callable[[dict[str, Any]], None] | None = None
        self._nlp_lexicon_coverage_samples: dict[str, list[tuple[float, float]]] = {}
        self._nlp_lexicon_coverage_breach_start: dict[str, float] = {}
        self._nlp_lexicon_coverage_last_alert: dict[str, float] = {}
        self._nlp_lexicon_coverage_window_s = 3600.0
        self._nlp_empty_input_samples: dict[str, list[tuple[float, int]]] = {}
        self._nlp_empty_input_last_alert: dict[str, float] = {}
        self._nlp_empty_input_window_s = float(getattr(cfg, "nlp_empty_input_anomaly_window_s", 300))
        self._nlp_empty_input_threshold = float(getattr(cfg, "nlp_empty_input_anomaly_threshold", 0.3))
        self._nlp_shout_samples: dict[str, list[tuple[float, int]]] = {}
        self._nlp_shout_last_alert: dict[str, float] = {}
        self._nlp_shout_window_s = float(getattr(cfg, "nlp_shout_rate_alert_window_s", 300))
        self._nlp_shout_threshold = float(getattr(cfg, "nlp_shout_rate_alert_threshold", 0.5))
        self._nlp_shout_min_requests = int(getattr(cfg, "nlp_shout_rate_alert_min_requests", 20))
        self._nlp_shout_alert_cooldown_s = float(getattr(cfg, "nlp_shout_rate_alert_cooldown_s", 600))
        self._nlp_sarcasm_cue_samples: dict[str, list[float]] = {}
        self._nlp_sarcasm_cue_last_alert: dict[str, float] = {}
        self._nlp_sarcasm_cue_window_s = float(getattr(cfg, "nlp_sarcasm_cue_drift_alert_window_s", 7 * 24 * 3600))
        self._nlp_sarcasm_cue_alert_cooldown_s = float(getattr(cfg, "nlp_sarcasm_cue_drift_alert_cooldown_s", 7 * 24 * 3600))
        # Phase 22.9 — Metric rename aliases for dual-emission window
        # Maps old_name → (new_name, registration_timestamp_utc)
        self._metric_aliases: dict[str, tuple[str, float]] = {}
        self._metric_rename_alias_days = float(getattr(cfg, "metric_rename_alias_days", 30))
        self._metric_rename_alias_window_s = self._metric_rename_alias_days * 86400

    @property
    def enabled(self) -> bool:
        return bool(self._redis_client())

    def _connect_redis(self) -> None:
        if self._redis_attempted_connection:
            return
        self._redis_attempted_connection = True
        try:
            import redis
            client = redis.Redis(**self._redis_config)
            client.ping()
            self._redis = client
            log.info(
                "Telemetry sink connected to Redis %s:%s",
                self._redis_config["host"],
                self._redis_config["port"],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis unavailable (%s) — telemetry disabled", exc)
            self._redis = None

    def _redis_client(self) -> Any | None:
        if self._redis is None and not self._redis_attempted_connection:
            self._connect_redis()
        return self._redis

    def register_alias(self, old_name: str, new_name: str) -> None:
        """
        Register a metric name alias for dual-emission during the rename window.
        
        During Phase 22.9 metric renames, both old and new metric names are emitted
        for cfg.metric_rename_alias_days (default 30) to allow dashboards and alert
        rules to transition gradually. After the window closes, the old name stops
        being emitted.
        
        Args:
            old_name: The deprecated metric name (e.g., "nlp_pipeline_latency_seconds")
            new_name: The conforming replacement name (e.g., "common_pipeline_latency_seconds")
        """
        self._metric_aliases[old_name] = (new_name, self._clock())
        log.debug(
            "Metric alias registered: %s → %s (30-day window)",
            old_name,
            new_name,
        )

    def is_alias_active(self, old_name: str) -> bool:
        """Check if a metric alias is still within its emission window."""
        if old_name not in self._metric_aliases:
            return False
        new_name, registered_at = self._metric_aliases[old_name]
        elapsed_s = self._clock() - registered_at
        return elapsed_s < self._metric_rename_alias_window_s

    def get_active_aliases(self) -> dict[str, str]:
        """Return dict of old_name → new_name for currently active aliases."""
        return {
            old: new
            for old, (new, reg_at) in self._metric_aliases.items()
            if (self._clock() - reg_at) < self._metric_rename_alias_window_s
        }

    # ── TQU classification events ────────────────────────

    def log_classification(
        self,
        raw_input: str,
        intent_id: str | None,
        confidence: float,
        success: bool,
    ) -> None:
        """Push one classification event to the stream."""
        client = self._redis_client()
        if not client:
            return
        entry: dict[str, Any] = {
            "ts": str(time.time()),
            "intent": intent_id or "none",
            "conf": str(round(confidence, 4)),
            "ok": str(int(success)),
            "input_len": str(len(raw_input)),
        }
        try:
            client.xadd(
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

    def record_nlp_prober_outcome(
        self,
        request_id: str,
        intent: str,
        success: bool,
        latency_seconds: float | None = None,
    ) -> None:
        """Log synthetic prober outcome events for audit and observability."""
        if len(str(request_id)) > 64 or len(str(intent)) > 64:
            log.warning("Refusing nlp_prober outcome log: ID/intent field suspiciously long")
            return

        entry: dict[str, str] = {
            "ts": str(time.time()),
            "request_id": request_id,
            "intent": intent or "unknown",
            "success": str(int(success)),
        }
        if latency_seconds is not None:
            entry["latency_seconds"] = f"{latency_seconds:.3f}"

        log.info(
            "NLP prober outcome",
            extra={
                "structured": True,
                **entry,
            },
        )

        if _PROMETHEUS_AVAILABLE and NLP_PROBER_SUCCESS_RATE:
            try:
                NLP_PROBER_SUCCESS_RATE.labels(intent=entry["intent"]).set(1.0 if success else 0.0)
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
        client = self._redis_client()
        if not client:
            return
        entry: dict[str, str] = {
            "ts": str(time.time()),
            "match_id": match_id,
            "volume": str(volume),
            "dist": json.dumps(distribution),
        }
        try:
            client.xadd(
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
        client = self._redis_client()
        if not client:
            return 0
        key = "negelir:qid:profiles"
        count = 0
        try:
            pipe = client.pipeline()
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
        client = self._redis_client()
        if not client:
            return {}
        key = "negelir:qid:profiles"
        try:
            raw = client.hgetall(key)
            return {k: json.loads(v) for k, v in raw.items()}
        except Exception:  # noqa: BLE001
            return {}

    # ── Stats ────────────────────────────────────────────

    def stream_lengths(self) -> dict[str, int]:
        """Return current stream lengths for monitoring."""
        client = self._redis_client()
        if not client:
            return {}
        try:
            return {
                "classifications": client.xlen(self._CLASSIFICATION_STREAM),
                "qid_snapshots": client.xlen(self._QID_STREAM),
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

    def record_nlp_empty_input_rate(self, subject: str, is_empty: bool) -> None:
        """
        Track per-subject empty-input rate and emit an alert when the abuse
        threshold is exceeded.
        """
        if not isinstance(subject, str) or not subject.strip():
            subject = "unknown"
        now = self._clock()
        samples = self._nlp_empty_input_samples.setdefault(subject, [])
        samples.append((now, 1 if is_empty else 0))
        cutoff = now - self._nlp_empty_input_window_s
        samples = [(ts, value) for ts, value in samples if ts >= cutoff]
        self._nlp_empty_input_samples[subject] = samples
        total_requests = len(samples)
        if total_requests == 0:
            return
        empty_requests = sum(value for _, value in samples)
        rate = empty_requests / float(total_requests)
        if _PROMETHEUS_AVAILABLE and NLP_EMPTY_INPUT_RATE_PER_SUBJECT:
            try:
                NLP_EMPTY_INPUT_RATE_PER_SUBJECT.labels(subject=subject).observe(rate)
            except Exception:  # noqa: BLE001
                pass  # non-blocking
        if total_requests < 20:
            return
        if rate <= self._nlp_empty_input_threshold:
            return
        last_alert = self._nlp_empty_input_last_alert.get(subject, float("-inf"))
        if now - last_alert < 600.0:
            return
        self._maybe_emit_nlp_alert(
            {
                "kind": "nlp_empty_input_anomaly_per_subject",
                "severity": "warn",
                "subject": subject,
                "reason": (
                    f"Empty input rate {rate:.3f} over the last "
                    f"{int(self._nlp_empty_input_window_s)}s for subject={subject}."
                ),
                "details": {
                    "rate": round(rate, 3),
                    "total_requests": total_requests,
                    "empty_requests": empty_requests,
                    "window_s": int(self._nlp_empty_input_window_s),
                },
                "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        self._nlp_empty_input_last_alert[subject] = now

    def record_nlp_input_shout(self, subject: str, is_shout: bool) -> tuple[bool, dict[str, object]]:
        """
        Track per-subject shout input rate and return alert details when the
        shout threshold is exceeded.
        """
        if not isinstance(subject, str) or not subject.strip():
            subject = "unknown"
        if not is_shout:
            return False, {}
        now = self._clock()
        samples = self._nlp_shout_samples.setdefault(subject, [])
        samples.append((now, 1))
        cutoff = now - self._nlp_shout_window_s
        samples = [(ts, value) for ts, value in samples if ts >= cutoff]
        self._nlp_shout_samples[subject] = samples
        total_requests = len(samples)
        shout_requests = sum(value for _, value in samples)
        if _PROMETHEUS_AVAILABLE and NLP_INPUT_SHOUT_TOTAL:
            try:
                NLP_INPUT_SHOUT_TOTAL.inc()
            except Exception:  # noqa: BLE001
                pass  # non-blocking
        if total_requests < self._nlp_shout_min_requests:
            return False, {}
        rate = shout_requests / float(total_requests)
        if rate <= self._nlp_shout_threshold:
            return False, {}
        last_alert = self._nlp_shout_last_alert.get(subject, float("-inf"))
        if now - last_alert < self._nlp_shout_alert_cooldown_s:
            return False, {}
        details = {
            "rate": round(rate, 3),
            "total_requests": total_requests,
            "shout_requests": shout_requests,
            "window_s": int(self._nlp_shout_window_s),
        }
        self._maybe_emit_nlp_alert(
            {
                "kind": "nlp_shout_rate_anomaly_per_subject",
                "severity": "warn",
                "subject": subject,
                "reason": (
                    f"Shout rate {rate:.3f} over the last {int(self._nlp_shout_window_s)}s for subject={subject}."
                ),
                "details": details,
                "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        self._nlp_shout_last_alert[subject] = now
        return True, details

    def record_nlp_sarcasm_cue(self, cue_id: str) -> None:
        """
        Record a sarcasm cue observation and emit a week-over-week drift alert.
        """
        if not isinstance(cue_id, str) or not cue_id.strip():
            cue_id = "unknown"
        if _PROMETHEUS_AVAILABLE and NLP_SARCASM_CUE_FIRE_RATE:
            try:
                NLP_SARCASM_CUE_FIRE_RATE.labels(cue_id=cue_id).observe(1.0)
            except Exception:  # noqa: BLE001
                pass

        now = self._clock()
        samples = self._nlp_sarcasm_cue_samples.setdefault(cue_id, [])
        samples.append(now)
        cutoff = now - 2.0 * self._nlp_sarcasm_cue_window_s
        samples = [ts for ts in samples if ts >= cutoff]
        self._nlp_sarcasm_cue_samples[cue_id] = samples

        prior_window_end = now - self._nlp_sarcasm_cue_window_s
        previous_count = sum(1 for ts in samples if cutoff <= ts < prior_window_end)
        current_count = sum(1 for ts in samples if ts >= prior_window_end)
        if previous_count < 5 or current_count < 5:
            return

        drift_ratio = abs(current_count - previous_count) / float(previous_count)
        if drift_ratio <= 0.5:
            return

        last_alert = self._nlp_sarcasm_cue_last_alert.get(cue_id, float("-inf"))
        if now - last_alert < self._nlp_sarcasm_cue_alert_cooldown_s:
            return

        self._maybe_emit_nlp_alert(
            {
                "kind": "sarcasm_cue_rate_drift",
                "severity": "info",
                "subject": cue_id,
                "reason": (
                    f"Week-over-week cue count for {cue_id!r} shifted "
                    f"from {previous_count} to {current_count}."
                ),
                "details": {
                    "cue_id": cue_id,
                    "previous_week_count": previous_count,
                    "current_week_count": current_count,
                    "drift_ratio": round(drift_ratio, 3),
                    "window_s": int(self._nlp_sarcasm_cue_window_s),
                },
                "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        self._nlp_sarcasm_cue_last_alert[cue_id] = now

    def record_nlp_lexicon_coverage(self, intent_class: str, coverage_ratio: float) -> None:
        """
        Record lexicon coverage for a single NLP query by intent class.

        Args:
            intent_class: Closed-set NLP intent class label.
            coverage_ratio: Fraction of resolvable tokens that hit the lexicon,
                expected in [0.0, 1.0].
        """
        if coverage_ratio < 0.0 or coverage_ratio > 1.0:
            return
        if _PROMETHEUS_AVAILABLE and NLP_LEXICON_COVERAGE:
            try:
                NLP_LEXICON_COVERAGE.labels(intent_class=intent_class).observe(coverage_ratio)
            except Exception:  # noqa: BLE001
                pass  # non-blocking
        self._record_nlp_lexicon_coverage_sample(intent_class, coverage_ratio)

    def register_nlp_alert_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback to receive NLP alert payloads from telemetry monitors."""
        self._alert_callback = callback

    def _maybe_emit_nlp_alert(self, payload: dict[str, Any]) -> None:
        if self._alert_callback is None:
            return
        try:
            self._alert_callback(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("Telemetry alert callback failed: %s", exc)

    def _record_nlp_lexicon_coverage_sample(self, intent_class: str, coverage_ratio: float) -> None:
        now = self._clock()
        samples = self._nlp_lexicon_coverage_samples.setdefault(intent_class, [])
        samples.append((now, coverage_ratio))
        cutoff = now - self._nlp_lexicon_coverage_window_s
        self._nlp_lexicon_coverage_samples[intent_class] = [
            (ts, ratio) for ts, ratio in samples if ts >= cutoff
        ]
        values = sorted(ratio for _, ratio in self._nlp_lexicon_coverage_samples[intent_class])
        if not values:
            return
        p50 = values[(len(values) - 1) // 2]
        floor = float(getattr(Config(), "nlp_lexicon_coverage_p50_floor", 0.6))
        if p50 < floor:
            breach_start = self._nlp_lexicon_coverage_breach_start.get(intent_class)
            if breach_start is None:
                self._nlp_lexicon_coverage_breach_start[intent_class] = now
                return
            if now - breach_start < 1800.0:
                return
            last_alert = self._nlp_lexicon_coverage_last_alert.get(intent_class, float("-inf"))
            if now - last_alert < 1800.0:
                return
            breaching = [
                c
                for c, start in self._nlp_lexicon_coverage_breach_start.items()
                if start is not None and now - start >= 1800.0
            ]
            severity = "error" if len(breaching) >= 2 else "warn"
            self._maybe_emit_nlp_alert(
                {
                    "kind": "lexicon_coverage_below_floor",
                    "severity": severity,
                    "subject": intent_class,
                    "reason": (
                        f"Lexicon coverage p50 for intent_class={intent_class} "
                        f"is {p50:.2f}, below floor {floor:.2f} over the last hour."
                    ),
                    "details": {
                        "intent_class": intent_class,
                        "observed_p50": round(p50, 3),
                        "window_s": self._nlp_lexicon_coverage_window_s,
                    },
                    "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            self._nlp_lexicon_coverage_last_alert[intent_class] = now
        else:
            self._nlp_lexicon_coverage_breach_start.pop(intent_class, None)

    def record_nlp_unresolved_token(self, token: str) -> None:
        """
        Track an unresolved token for the hourly top-k report.

        Token values longer than the configured unredacted threshold are
        replaced with a sha8-prefixed redaction placeholder to avoid PII
        leakage.
        """
        if not token:
            return
        try:
            now = time.monotonic()
            if now - self._unresolved_token_window_start >= self._unresolved_token_window_s:
                self._unresolved_token_counts.clear()
                self._unresolved_token_window_start = now

            if len(token) >= self._unresolved_token_max_unredacted_len:
                token = f"[REDACTED:len={len(token)}:sha8={hashlib.sha256(token.encode('utf-8')).hexdigest()[:8].upper()}]"

            self._unresolved_token_counts[token] += 1
            if len(self._unresolved_token_counts) > self._unresolved_token_top_k:
                self._prune_unresolved_tokens()
        except Exception:  # noqa: BLE001
            pass  # non-blocking

    def _prune_unresolved_tokens(self) -> None:
        """Keep only the top-k unresolved token counts.

        This protects the in-memory rolling window from unbounded growth.
        """
        if len(self._unresolved_token_counts) <= self._unresolved_token_top_k:
            return
        self._unresolved_token_counts = collections.Counter(
            dict(self._unresolved_token_counts.most_common(self._unresolved_token_top_k))
        )

    def get_nlp_unresolved_top_k(self, k: int | None = None) -> list[tuple[str, int]]:
        """Return the current unresolved token top-k list."""
        if k is None:
            k = self._unresolved_token_top_k
        return self._unresolved_token_counts.most_common(k)

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

    def record_nlp_eval_corpus_growth_rate(self, intent_class: str, new_rows: float) -> None:
        """
        Observe the number of new eval corpus rows added for the given intent class.
        """
        if new_rows < 0:
            return
        if _PROMETHEUS_AVAILABLE and NLP_EVAL_CORPUS_GROWTH_RATE:
            try:
                NLP_EVAL_CORPUS_GROWTH_RATE.labels(intent_class=intent_class).observe(new_rows)
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
