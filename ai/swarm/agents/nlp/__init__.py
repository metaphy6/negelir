"""Phase 10 §10.0 — NLP plane agent stubs (boundary-discipline skeletons).

Three agents land here per ROADMAP §10.0 wire-authority:

* ``nlp.intent.v1``    — subscribes ``qa.request.v1`` (sanitized
                         data-plane, NEVER the raw ``qa.request``
                         control-plane); normalizes, classifies intent,
                         extracts entities; publishes ``qa.intent.v1``
                         (consumed by the future nlp.dispatcher.v1,
                         §10.6) + ``nlp.event.v1`` / ``nlp.alert.v1``
                         for observability.

* ``nlp.answer.v1``    — subscribes ``qa.intent.v1`` (structured intent
                         envelope) and ``predict.approved.v1`` (Phase 6
                         gated; NEVER ``predict.final`` — that is the
                         unvetted candidate); assembles the Turkish-
                         language answer from templates (§10.7);
                         publishes ``qa.answer.v1`` +
                         ``nlp.event.v1`` / ``nlp.alert.v1``.

* ``nlp.proofreader.v1`` — subscribes ``qa.answer.v1`` (pre-clean
                           answer); performs PII detection + redaction
                           (§10.9); republishes to ``qa.answer.v1``
                           (clean path) + ``nlp.event.v1`` /
                           ``nlp.alert.v1``.

These skeletons carry the correct ``name``, ``subscribes``, and
``publishes`` class attributes so the Phase 10 boundary tests in
``test_boundary_discipline.py`` can import them and assert the wire
contract via registry walk.  Full handler logic lands per-bullet in
§10.1–§10.20; until then every ``handle()`` is a no-op that returns
an empty iterable.

Boundary invariants (all asserted by Rule 11 in
``test_boundary_discipline.py``):

* NLP NEVER subscribes to raw ``qa.request`` (control-plane).  Only
  ``qa.request.v1`` (sanitized data-plane).  Mirrors §7.5 doctrine.
* NLP NEVER subscribes to ``predict.final`` (Phase 5 candidate).
  Only ``predict.approved.v1`` (Phase 6 gated).
* NLP NEVER publishes to ``sec.*``, ``maint.*``, ``auth.*``,
  ``payment.*``, ``patcher.*``.  Outbound set is exactly
  ``{qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1,
    predict.request.v1, data.request.v1}``.
* NLP NEVER writes to Postgres directly.
"""
from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import hmac as _hmac
import logging
import threading as _threading
import time as _time
from typing import Callable, Iterable
import os
from pathlib import Path
import stat
from uuid import uuid4

from common.security.patterns import PII_PATTERNS

from ...sdk.types import Message
from ..topics import (
    DATA_REQUEST_V1,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    PREDICT_APPROVED,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_INTENT_V1,
    QA_REQUEST_V1,
)
from ._bus_circuit_breaker import NlpBusCircuitBreaker
from ._log_filter import PIIScrubFilter, add_log_filter

# ── internal helpers ──────────────────────────────────────────────────────

# Entity kinds that can anchor a predict.* intent to a specific fixture.
_FIXTURE_ENTITY_KINDS = frozenset({"team", "competition"})

# Summary intents that fan-out to multiple predict.request.v1 messages.
_SUMMARY_INTENTS = frozenset({"summary.next_week", "summary.matchday"})

# Maximum number of dedup keys held in each NLP agent's LRU (structural cap;
# not a config knob because it is a data-structure bound, not a tunable
# threshold — the window_s config is the user-facing knob).
_NLP_DEDUP_MAX_KEYS: int = 100_000
_MOCK_PREDICT_CITATION_HMAC_KEY: bytes = b"negelir:mock:predict:citation:hmac:v1"


AUDIT_REDACTION_WHITELIST = frozenset(
    {
        "qa_correlation_id",
        "request_id",
        "intent",
        "intent_confidence",
        "entity_count",
        "proofreader_status",
        "humanizer_used",
        "degraded",
        "degraded_reason",
        "tier_id_required",
        "model_versions",
        "calibration_version",
        "nlp_pipeline_version",
        "lexicon_versions",
        "produced_at_utc",
    }
)


def _redact_text_with_pii_patterns(value: str) -> str:
    redacted = value
    for pii_kind, pii_pattern in PII_PATTERNS:
        redacted = pii_pattern.sub(
            f"[REDACTED_{pii_kind.upper()}]",
            redacted,
        )
    return redacted


def _redact_value_with_pii_patterns(value: object) -> object:
    if isinstance(value, str):
        return _redact_text_with_pii_patterns(value)
    if isinstance(value, list):
        return [_redact_value_with_pii_patterns(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_value_with_pii_patterns(item)
            for key, item in value.items()
        }
    return value


def _entity_hash(entities: list) -> str:
    """Stable 16-hex-char hash of the sorted canonical_id set in *entities*.

    Used as the third component of the §10.6 dispatcher idempotency key
    ``(qa_correlation_id, intent, entity_hash)``.
    """
    sorted_ids = sorted(
        str(e.get("canonical_id") or "") for e in entities
    )
    return _hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()[:16]


def audit_key(
    qa_correlation_id: str, intent_model_version: str, calibration_version: str
) -> str:
    """§10.13 audit key: stable hash of (qa_correlation_id, intent_model_version,
    calibration_version).

    Two requests with the same qa_correlation_id but different model/calibration
    versions MUST produce distinct qa.answer.v1 envelopes; this key is used for
    audit logging and ensuring distinct envelopes.

    Returns a 16-hex-char sha256 prefix.
    """
    components = f"{qa_correlation_id}|{intent_model_version}|{calibration_version}"
    return _hashlib.sha256(components.encode()).hexdigest()[:16]


def cache_key_for_intent(
    intent: str,
    entity_hash: str,
    fixture_window_bucket: str,
    model_versions_hash: str,
    intent_model_version: str,
    calibration_version: str,
) -> str:
    """§10.12 L1 answer cache key including model/calibration versions per §10.13.

    Key = sha256(intent | entity_hash | fixture_window_bucket | model_versions_hash |
                 intent_model_version | calibration_version).

    Returns a 16-hex-char sha256 prefix.
    """
    components = (
        f"{intent}|{entity_hash}|{fixture_window_bucket}|{model_versions_hash}|"
        f"{intent_model_version}|{calibration_version}"
    )
    return _hashlib.sha256(components.encode()).hexdigest()[:16]


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _enforce_nlp_spool_audit_dir_modes() -> None:
    """Refuse startup when NLP spool/audit files are looser than 0600.

    Directory contract: ``0700`` for ``cfg.nlp_agent_spool_dir`` and
    ``data/nlp/audit`` (including subdirectories).
    File contract: ``0600`` for every existing file under those trees.
    """
    if os.name != "posix":
        return

    from common.config import cfg

    targets = [
        Path(str(cfg.nlp_agent_spool_dir)),
        Path("data") / "nlp" / "audit",
    ]
    violations: list[str] = []

    for root in targets:
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)

        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                continue
            if path.is_dir():
                os.chmod(path, 0o700)
                continue
            if path.is_file():
                mode = stat.S_IMODE(path.stat().st_mode)
                if mode != 0o600:
                    violations.append(f"{path}: expected 0600, got {mode:04o}")

    if violations:
        raise RuntimeError(
            "NLP startup refused: insecure spool/audit file modes; "
            + "; ".join(violations)
        )


class _SummaryAgg:
    """In-flight aggregation state for a summary.* fan-out (§10.6)."""

    __slots__ = ("expected", "qa_request_id", "qa_correlation_id", "deadline", "predictions")

    def __init__(
        self,
        expected: int,
        qa_request_id: str,
        qa_correlation_id: str,
        deadline: float,
    ) -> None:
        self.expected = expected
        self.qa_request_id = qa_request_id
        # §10.6 qa_correlation_id invariant — read from predict.approved.v1
        # (additive Phase 5 field); defaults to summary_correlation_id so the
        # single-value case (`summary_corr`) is backward-compatible.
        self.qa_correlation_id = qa_correlation_id
        self.deadline = deadline  # monotonic timestamp
        self.predictions: list = []


class NlpBootProbeState:
    """Tracks probe state so liveness and readiness are not conflated.

    Phase 10 §10.21.9 starts with the failure mode where a pod is alive but
    still booting NLP assets. This state object makes that distinction
    explicit: liveness can be true while readiness is still false.
    """

    _STAGE_NAMES = (
        "starting",
        "lexicons_loaded",
        "intent_model_loaded",
        "crf_loaded",
        "symspell_built",
        "jinja_warmed",
        "gpu_lease_acquired_or_skipped",
    )

    __slots__ = (
        "_lock",
        "_stage",
        "_clock_iso",
        "_monotonic",
        "_boot_started_s",
        "_boot_budget_s",
        "_boot_liveness_grace_s",
        "_stage_caps_s",
        "_timed_out",
    )

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        boot_budget_s: float | None = None,
        boot_liveness_grace_s: float | None = None,
        stage_caps_s: dict[int, float] | None = None,
    ) -> None:
        self._lock = _threading.Lock()
        self._stage = 0
        self._clock_iso = clock_iso or (
            lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        )
        self._monotonic = monotonic or _time.monotonic
        self._boot_started_s = self._monotonic()
        if boot_budget_s is None or boot_liveness_grace_s is None:
            from common.config import cfg
            if boot_budget_s is None:
                boot_budget_s = float(cfg.nlp_boot_budget_s)
            if boot_liveness_grace_s is None:
                boot_liveness_grace_s = float(cfg.nlp_boot_liveness_grace_s)
        self._boot_budget_s = float(boot_budget_s)
        self._boot_liveness_grace_s = float(boot_liveness_grace_s)
        self._stage_caps_s = stage_caps_s or {
            1: 10.0,
            2: 3.0,
            3: 2.0,
            4: 10.0,
            5: 2.0,
            6: 3.0,
        }
        self._timed_out = False

    def liveness(self) -> bool:
        """Process liveness with boot-timeout grace for K8s restart handoff."""
        with self._lock:
            ready = self._stage >= len(self._STAGE_NAMES) - 1 and not self._timed_out
            timed_out = self._timed_out
        if ready or not timed_out:
            return True
        elapsed_s = self._monotonic() - self._boot_started_s
        return elapsed_s < self._boot_liveness_grace_s

    def readiness(self) -> bool:
        """Traffic readiness: false until boot stage 6 is reached."""
        with self._lock:
            return (not self._timed_out) and self._stage >= len(self._STAGE_NAMES) - 1

    def startup_readiness(self) -> bool:
        """Startup probe readiness: true once lexicons are loaded (stage >= 1)."""
        with self._lock:
            return self._stage >= 1

    def _build_boot_timeout_alert(self, *, producer: str, reason: str, last_stage: int) -> Message:
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "schema_version": 1,
                "alert_id": _new_id(),
                "kind": "nlp_cold_start_timeout",
                "severity": "critical",
                "source": producer,
                "reason": reason,
                "request_id": None,
                "qa_correlation_id": None,
                "details": {
                    "last_stage": last_stage,
                    "last_stage_name": self._STAGE_NAMES[last_stage],
                    "boot_budget_s": self._boot_budget_s,
                },
                "emitted_at": self._clock_iso(),
            },
            producer=producer,
        )

    def stage(self) -> int:
        """Return the current monotonic boot stage index."""
        with self._lock:
            return self._stage

    def mark_stage(self, stage: int, elapsed_ms: int, producer: str = "nlp.intent.v1") -> Message:
        """Advance stage monotonically and emit ``nlp.event.v1{kind=cold_start_stage}``."""
        if stage < 0 or stage >= len(self._STAGE_NAMES):
            raise ValueError(f"invalid boot stage: {stage}")
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be >= 0")

        timeout_reason: str | None = None
        last_stage = 0

        with self._lock:
            if stage < self._stage:
                raise ValueError(
                    f"boot stage regression: current={self._stage} attempted={stage}"
                )
            last_stage = self._stage
            if self._timed_out:
                timeout_reason = "boot_budget_already_breached"
            else:
                stage_cap_s = self._stage_caps_s.get(stage)
                if stage_cap_s is not None and (elapsed_ms / 1000.0) > stage_cap_s:
                    self._timed_out = True
                    timeout_reason = "stage_cap_breached"
                elif (self._monotonic() - self._boot_started_s) > self._boot_budget_s:
                    self._timed_out = True
                    timeout_reason = "total_boot_budget_breached"
                else:
                    self._stage = stage

        if timeout_reason is not None:
            return self._build_boot_timeout_alert(
                producer=producer,
                reason=timeout_reason,
                last_stage=last_stage,
            )

        return Message.new(
            topic=NLP_EVENT_V1,
            payload={
                "kind": "cold_start_stage",
                "producer": producer,
                "request_id": None,
                "stage": stage,
                "stage_name": self._STAGE_NAMES[stage],
                "elapsed_ms": elapsed_ms,
                "emitted_at": self._clock_iso(),
            },
            producer=producer,
        )

    def mark_ready(self) -> None:
        """Compatibility helper: mark probe as fully booted (stage 6)."""
        with self._lock:
            if not self._timed_out:
                self._stage = len(self._STAGE_NAMES) - 1


class NlpIntentAgent:
    """Phase 10 §10.0–§10.5 skeleton: normalize + classify + extract.

    Subscribes to ``qa.request.v1`` (the sec-sanitized data-plane
    envelope, NEVER the raw ``qa.request`` control-plane).  Publishes
    ``qa.intent.v1`` carrying the structured intent + entity set, plus
    ``nlp.event.v1`` / ``nlp.alert.v1`` for operational observability.
    """

    name = "nlp.intent.v1"
    subscribes = [QA_REQUEST_V1]
    publishes = [QA_INTENT_V1, NLP_EVENT_V1, NLP_ALERT_V1]

    def __init__(
        self,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.intent")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._monotonic = monotonic or _time.monotonic
        _enforce_nlp_spool_audit_dir_modes()
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()

    def _get_deduper(self) -> object:
        """Return the intent deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_request_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def handle(self, msg: Message) -> Iterable[Message]:
        """Process qa.request.v1 → qa.intent.v1 (stub for §10.1–§10.5).

        §10.13 idempotency: dedup on request_id at ingress.
        """
        request_id = str(msg.payload.get("request_id", ""))
        if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
            return []
        # Stub: full implementation lands in §10.1–§10.5 bullets.
        return []


class NlpDispatcherAgent:
    """Phase 10 §10.6 skeleton: slot resolver + bus dispatch.

    Subscribes to ``qa.intent.v1`` (structured intent + entities).
    Translates ``(intent, entities)`` to exactly one of:

    * ``predict.request.v1`` — for any ``predict.*`` intent that fully
      resolves to a single fixture + market.
    * ``data.request.v1``    — for ``data.*`` intents (Phase 4 storage
      agent answers).
    * ``qa.answer.v1``       — directly for ``meta.*`` intents (no
      compute needed) or ``kind=disambiguation`` when slot resolution
      surfaces multiple plausible fixtures.

    Also emits ``nlp.event.v1{kind=slot_resolution_failed}`` when
    disambiguation is required, and ``nlp.alert.v1`` on error.

    §10.6 deterministic backoff (this bullet):
    When intent is ``predict.*`` but no fixture-anchoring entity
    (``team`` or ``competition`` kind) is present, the dispatcher MUST
    NOT default to "today's headline match".  It emits
    ``qa.answer.v1{kind=disambiguation}`` so the user can specify which
    match they mean.  The ``fixture_window_h`` in the metadata comes
    from ``cfg.nlp_default_fixture_window_h`` (§10.19 config key).
    """

    name = "nlp.dispatcher.v1"
    subscribes = [QA_INTENT_V1]
    publishes = [
        PREDICT_REQUEST_V1,
        DATA_REQUEST_V1,
        QA_ANSWER_V1,
        NLP_EVENT_V1,
        NLP_ALERT_V1,
    ]

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.dispatcher")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._clock_iso = clock_iso or _utc_iso
        _enforce_nlp_spool_audit_dir_modes()
        self._new_id = new_id or _new_id
        self._monotonic = monotonic or _time.monotonic
        # §10.6 idempotency: lazy-init deduper (cfg not available at class load).
        self._deduper = deduper  # None → created on first handle() call
        self._deduper_lock = _threading.Lock()

    def _get_deduper(self) -> object:
        """Return the dispatcher deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_dispatch_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def handle(self, msg: Message) -> Iterable[Message]:
        """Route qa.intent.v1 to the appropriate downstream action.

        §10.6 backoff: predict.* intent without a resolvable fixture
        entity → emit qa.answer.v1{kind=disambiguation}.
        §10.6 multi-fixture: summary.* intent → fan-out N
        predict.request.v1 with shared summary_correlation_id.
        §10.6 idempotency: (qa_correlation_id, intent, entity_hash) dedup
        key suppresses replayed qa.intent.v1 messages within the window.
        All other routing paths remain stubs (future bullets).
        """
        from common.config import cfg  # local import avoids circular at module load

        payload = msg.payload
        intent: str = str(payload.get("intent", ""))
        entities: list = list(payload.get("entities", []))
        request_id: str = str(payload.get("request_id", ""))

        # ── §10.6 idempotency — dedup before any routing ───────────────────
        qa_corr_in: str = str(payload.get("qa_correlation_id") or "")
        dedup_key = f"{qa_corr_in}:{intent}:{_entity_hash(entities)}"
        if self._get_deduper().seen(dedup_key):  # type: ignore[union-attr]
            return []

        # ── §10.6 multi-fixture fan-out ────────────────────────────────────
        if intent in _SUMMARY_INTENTS:
            fixture_entities = [
                e for e in entities
                if e.get("kind") in _FIXTURE_ENTITY_KINDS and e.get("canonical_id")
            ]
            if not fixture_entities:
                # No fixture anchors → disambiguation
                return self._make_disambiguation(request_id, intent, cfg)
            max_f = cfg.nlp_summary_max_fixtures
            capped = fixture_entities[:max_f]
            summary_corr = self._new_id()
            expected_count = len(capped)
            out: list[Message] = []
            for entity in capped:
                out.append(
                    Message.new(
                        topic=PREDICT_REQUEST_V1,
                        payload={
                            "match_id": entity["canonical_id"],
                            "market": "1x2",
                            "request_id": self._new_id(),
                            "qa_correlation_id": summary_corr,
                            "qa_request_id": request_id,
                            "summary_correlation_id": summary_corr,
                            "summary_expected_count": expected_count,
                            "league_id": entity.get("league_id"),
                            "profile_id": None,
                            "emitted_at": self._clock_iso(),
                        },
                        producer=self.name,
                    )
                )
            return out

        # ── §10.6 deterministic backoff ────────────────────────────────────
        if intent.startswith("predict."):
            # Check for fixture-anchoring entities (team or competition).
            has_fixture_entity = any(
                e.get("kind") in _FIXTURE_ENTITY_KINDS and e.get("canonical_id")
                for e in entities
            )
            if not has_fixture_entity:
                # §10.6 deterministic backoff — never guess a headline match.
                return self._make_disambiguation(request_id, intent, cfg)
            # predict.* with resolvable fixture: routing to predict.request.v1
            # implemented in subsequent §10.6 bullets.

        # data.*, meta.*, and resolvable predict.* routing: future bullets.
        return []

    def _make_disambiguation(
        self, request_id: str, intent: str, cfg: object
    ) -> list[Message]:
        """Emit qa.answer.v1{kind=disambiguation} (shared helper)."""
        qa_correlation_id = self._new_id()
        tier_id_required = self._tier_id_required_for_intent(intent, cfg)
        window_h = getattr(cfg, "nlp_default_fixture_window_h", 48)
        answer_text = (
            f"Hangi maç için tahmin istiyorsunuz? "
            f"Önümüzdeki {window_h} saat içindeki maçları listeleyebilirim."
        )
        return [
            Message.new(
                topic=QA_ANSWER_V1,
                payload={
                    "request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "answer_text": answer_text,
                    "intent": intent,
                    "kind": "disambiguation",
                    "degraded": False,
                    "degraded_reason": None,
                    "tier_id_required": tier_id_required,
                    "citations": [],
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

    def _tier_id_required_for_intent(self, intent: str, cfg: object) -> str | None:
        """Resolve tier label from cfg.nlp_intent_tier_map using intent only."""
        tier_map = getattr(cfg, "nlp_intent_tier_map", {})
        if not isinstance(tier_map, dict):
            return None
        tier_value = tier_map.get(intent)
        if tier_value is None:
            return None
        normalized = str(tier_value).strip()
        return normalized or None

    def _check_backpressure(self, queue_depth: int) -> bool:
        """§10.19 backpressure stub: returns True when pressure is active.

        When qa.intent.v1 queue depth > cfg.nlp_queue_pressure_threshold:
        (a) disable humanizer (template-only mode) for cfg.nlp_pressure_humanize_off_s;
        (b) widen nlp_intent_cache_ttl_s 2x;
        (c) emit nlp.alert.v1{kind=nlp_queue_pressure, severity=warn} (debounced 60s).

        Full implementation lands in subsequent §10.19 bullets. This stub
        returns True when queue_depth exceeds the threshold, False otherwise.
        """
        from common.config import cfg

        threshold = cfg.nlp_queue_pressure_threshold
        return queue_depth > threshold


class NlpAnswerAgent:
    """Phase 10 §10.6–§10.7 skeleton: dispatch + answer assembly.

    Subscribes to ``qa.intent.v1`` (structured intent) and
    ``predict.approved.v1`` (Phase 6 proofreader-gated; NEVER
    ``predict.final`` — the unvetted candidate).  Publishes the
    Turkish-language answer on ``qa.answer.v1``.

    §10.6 multi-fixture aggregation: when ``predict.approved.v1``
    carries ``summary_correlation_id``, the agent accumulates arrivals
    up to ``expected_count`` within ``cfg.nlp_summary_aggregation_timeout_ms``.
    On completion *or* timeout it emits a single ``qa.answer.v1``
    (degraded=True with "X / Y maç hazır" note if under-collected).
    """

    name = "nlp.answer.v1"
    subscribes = [QA_INTENT_V1, PREDICT_APPROVED]
    publishes = [QA_ANSWER_V1, NLP_EVENT_V1, NLP_ALERT_V1]

    def __init__(
        self,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.answer")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._clock_iso = clock_iso or _utc_iso
        _enforce_nlp_spool_audit_dir_modes()
        self._new_id = new_id or _new_id
        self._monotonic = monotonic or _time.monotonic
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()
        # Aggregation state for in-flight summary fan-outs.
        # Keyed by summary_correlation_id.
        self._pending_summaries: dict[str, _SummaryAgg] = {}
        self._lock = _threading.Lock()
        # §10.19 sampled answer audit state.
        self._audit_today_count = 0
        self._audit_date = ""
        self._audit_lock = _threading.Lock()

    def _get_deduper(self) -> object:
        """Return the answer deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_request_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def _maybe_audit_answer(
        self, answer_text: str, envelope: dict, qa_correlation_id: str
    ) -> None:
        """§10.19 sampled answer audit — capture 1-in-N answers (PII-redacted).

        Samples 1-in-cfg.nlp_answer_sample_inverse answers and writes them to
        ``data/nlp/audit/<YYYY-MM-DD>/<qa_correlation_id>.json`` for offline
        quality review. PII-redacts the answer text (email/phone regex) before
        writing. Enforces daily cap via in-memory counter (resets on date change).

        Silently skips on any I/O error (never blocks the user).
        """
        import json
        import os
        import random

        from common.config import cfg

        # Sample 1-in-N
        if random.randint(1, cfg.nlp_answer_sample_inverse) != 1:
            return

        with self._audit_lock:
            today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
            # Reset counter on date change.
            if self._audit_date != today:
                self._audit_date = today
                self._audit_today_count = 0

            # Check daily cap.
            if self._audit_today_count >= cfg.nlp_answer_sample_daily_cap:
                return

            self._audit_today_count += 1

        redacted_text = _redact_text_with_pii_patterns(answer_text)
        redacted_envelope = {
            key: (
                value
                if key in AUDIT_REDACTION_WHITELIST
                else _redact_value_with_pii_patterns(value)
            )
            for key, value in envelope.items()
        }

        # Prepare audit payload.
        audit_payload = {
            "qa_correlation_id": qa_correlation_id,
            "answer_text_redacted": redacted_text,
            "envelope": redacted_envelope,
            "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"
            ),
        }

        # Write to disk (fail silently).
        try:
            audit_dir = os.path.join("data", "nlp", "audit", today)
            os.makedirs(audit_dir, exist_ok=True)
            audit_path = os.path.join(audit_dir, f"{qa_correlation_id}.json")
            with open(audit_path, "w", encoding="utf-8") as fh:
                json.dump(audit_payload, fh, ensure_ascii=False, indent=2)
            os.chmod(audit_path, 0o600)
        except OSError:
            # Fail silently — never block the user on audit I/O error.
            pass

    def handle(self, msg: Message) -> Iterable[Message]:
        """Route by topic: qa.intent.v1 or predict.approved.v1.

        §10.13 idempotency: qa.intent.v1 deduped on request_id at ingress;
        predict.approved.v1 with summary aggregation is implicitly deduped
        by summary_correlation_id key in _pending_summaries.
        """
        topic = msg.envelope.topic
        if topic == QA_INTENT_V1:
            request_id = str(msg.payload.get("request_id", ""))
            if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
                return []
            # Stub: full implementation lands in future bullets.
            return []
        if topic == PREDICT_APPROVED:
            return self._on_predict_approved(msg)
        return []

    def _on_predict_approved(self, msg: Message) -> Iterable[Message]:
        payload = msg.payload
        citation_check = self._validate_citation_signature(payload)
        if citation_check is not None:
            alert = self._build_citation_signature_alert(payload, citation_check)
            if citation_check["mode"] == "enforce":
                return [
                    self._build_predict_timeout_answer(payload),
                    alert,
                ]

        summary_corr = payload.get("summary_correlation_id")
        if summary_corr:
            out = list(self._on_summary_prediction_arrived(payload, str(summary_corr)))
            if citation_check is not None:
                out.append(alert)
            return out
        # Single-predict path: stub for future §10.7 bullets.
        if citation_check is not None:
            return [alert]
        return []

    def _citation_key_id(self, key: bytes) -> str:
        return _hashlib.sha256(key).hexdigest()[:16]

    def _load_predict_citation_hmac_keys(self) -> dict[str, bytes]:
        from common.config import cfg

        loaded: dict[str, bytes] = {}
        key_path = str(getattr(cfg, "predict_citation_hmac_key_path", "") or "").strip()
        grace_s = int(getattr(cfg, "predict_citation_hmac_key_grace_s", 86_400) or 0)
        if key_path:
            path = Path(key_path).expanduser()
            try:
                key = path.read_bytes().strip()
                if key:
                    loaded[self._citation_key_id(key)] = key
                    if grace_s > 0:
                        current_age_s = max(0.0, _time.time() - path.stat().st_mtime)
                        if current_age_s <= grace_s:
                            prev_path = Path(f"{path}.prev")
                            if prev_path.exists():
                                prev_key = prev_path.read_bytes().strip()
                                if prev_key:
                                    loaded[self._citation_key_id(prev_key)] = prev_key
            except OSError:
                pass

        if str(getattr(cfg, "profile", "mock")).lower() == "mock":
            loaded[self._citation_key_id(_MOCK_PREDICT_CITATION_HMAC_KEY)] = _MOCK_PREDICT_CITATION_HMAC_KEY
        return loaded

    def _compute_expected_citation_signature(self, payload: dict, key: bytes) -> str:
        final = payload.get("final") if isinstance(payload.get("final"), dict) else {}
        prediction_id = str(payload.get("prediction_id") or "")
        produced_at = str(final.get("produced_at") or payload.get("approved_at") or "")
        model_versions = final.get("contributing_models")
        if not isinstance(model_versions, list):
            model_versions = []
        canonical_models = "|".join(sorted(str(mid) for mid in model_versions))
        calibration_version = int(payload.get("calibration_version") or final.get("calibration_version") or 1)
        blob = f"{prediction_id}|{produced_at}|{canonical_models}|{calibration_version}"
        return _hmac.new(key, blob.encode("utf-8"), _hashlib.sha256).hexdigest()

    def _validate_citation_signature(self, payload: dict) -> dict | None:
        from common.config import cfg

        schema_version = int(payload.get("schema_version") or 1)
        if schema_version < 3 and "citation_signature" not in payload:
            # Backward-compatibility path: pre-v3 approved envelopes did not
            # carry citation signatures, so they are consumed as-is.
            return None

        mode = str(getattr(cfg, "nlp_predict_citation_hmac_required", "warn") or "warn").lower()
        if mode == "off":
            return None

        keys = self._load_predict_citation_hmac_keys()
        if not keys:
            return {"mode": mode, "reason": "citation_hmac_key_unavailable"}

        signature = payload.get("citation_signature")
        if signature is None:
            return {"mode": mode, "reason": "citation_signature_missing"}
        observed = str(signature).strip().lower()
        if not observed:
            return {"mode": mode, "reason": "citation_signature_missing"}

        key_id = payload.get("citation_key_id")
        if key_id is not None:
            selected = keys.get(str(key_id).strip().lower())
            if selected is None:
                return {"mode": mode, "reason": "citation_key_id_unknown"}
            expected = self._compute_expected_citation_signature(payload, selected)
            if not _hmac.compare_digest(observed, expected):
                return {"mode": mode, "reason": "citation_signature_invalid"}
            return None

        # Backward compatibility path: older producers may not stamp key id.
        if not any(
            _hmac.compare_digest(observed, self._compute_expected_citation_signature(payload, key))
            for key in keys.values()
        ):
            return {"mode": mode, "reason": "citation_signature_invalid"}

        return None

    def _build_citation_signature_alert(self, payload: dict, check: dict) -> Message:
        severity = "critical" if check["mode"] == "enforce" else "warn"
        reason = str(check.get("reason") or "citation_signature_invalid")
        return Message.new(
            topic=NLP_ALERT_V1,
            payload={
                "schema_version": 1,
                "alert_id": self._new_id(),
                "kind": "nlp_citation_signature_verify_failed",
                "severity": severity,
                "source": self.name,
                "reason": reason,
                "request_id": str(payload.get("qa_request_id") or "") or None,
                "qa_correlation_id": (
                    str(payload.get("qa_correlation_id") or payload.get("summary_correlation_id") or "") or None
                ),
                "details": {
                    "mode": check["mode"],
                    "prediction_id": str(payload.get("prediction_id") or ""),
                },
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _build_predict_timeout_answer(self, payload: dict) -> Message:
        request_id = str(payload.get("qa_request_id") or payload.get("request_id") or "")
        qa_correlation_id = str(
            payload.get("qa_correlation_id")
            or payload.get("summary_correlation_id")
            or self._new_id()
        )
        return Message.new(
            topic=QA_ANSWER_V1,
            payload={
                "request_id": request_id,
                "qa_correlation_id": qa_correlation_id,
                "intent": "predict.timeout",
                "answer_text": "Tahmin zaman aşımına uğradı.",
                "kind": "predict.timeout",
                "degraded": True,
                "degraded_reason": "citation_signature_verification_failed",
                "tier_id_required": None,
                "citations": [],
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )

    def _on_summary_prediction_arrived(
        self, payload: dict, summary_corr: str
    ) -> Iterable[Message]:
        from common.config import cfg

        with self._lock:
            agg = self._pending_summaries.get(summary_corr)
            if agg is None:
                expected = int(payload.get("summary_expected_count", 1))
                qa_request_id = str(payload.get("qa_request_id", ""))
                # §10.6 qa_correlation_id invariant: read the additive Phase 5
                # field from predict.approved.v1; fall back to summary_corr so
                # old approved envelopes that pre-date the additive field still
                # work (backward-compatible).
                qa_correlation_id = str(
                    payload.get("qa_correlation_id") or summary_corr
                )
                timeout_s = cfg.nlp_summary_aggregation_timeout_ms / 1000.0
                agg = _SummaryAgg(
                    expected=expected,
                    qa_request_id=qa_request_id,
                    qa_correlation_id=qa_correlation_id,
                    deadline=self._monotonic() + timeout_s,
                )
                self._pending_summaries[summary_corr] = agg
            agg.predictions.append(payload)
            received = len(agg.predictions)
            expired = self._monotonic() > agg.deadline
            complete = received >= agg.expected

            if complete or expired:
                del self._pending_summaries[summary_corr]
                return [self._build_summary_answer(agg, summary_corr, received)]
        return []

    def _build_summary_answer(
        self, agg: _SummaryAgg, summary_corr: str, received: int
    ) -> Message:
        from common.config import cfg

        # §10.16 hard rule: preserve degraded flag from predict.approved.v1.
        # Check if ANY prediction in the aggregation has degraded=True in its
        # final payload (predict.approved.v1 embeds predict.final under "final").
        # Combine timeout-degraded with prediction-degraded via OR.
        timeout_degraded = received < agg.expected
        prediction_degraded = False
        degraded_reasons: list[str] = []
        
        # §10.16 calibration version stamping: group predictions by
        # calibration_version; emit one citation entry per unique version.
        calibration_groups: dict[int, int] = {}
        prediction_links: list[str] = []
        
        for pred in agg.predictions:
            final = pred.get("final", {})
            if final.get("degraded"):
                prediction_degraded = True
                reason = final.get("degraded_reason", "")
                if reason:  # Only add non-empty reasons
                    degraded_reasons.append(reason)
            
            # Track calibration_version from predict.approved.v1 (top-level).
            cal_ver = int(pred.get("calibration_version", 1))
            calibration_groups[cal_ver] = calibration_groups.get(cal_ver, 0) + 1
            prediction_id = str(pred.get("prediction_id") or "").strip()
            if prediction_id:
                prediction_links.append(f"/tahmin/{prediction_id}")
        
        degraded = timeout_degraded or prediction_degraded
        
        if timeout_degraded:
            degraded_reasons.insert(
                0, f"{received}/{agg.expected} predictions received before timeout"
            )
        
        if degraded:
            answer_text = (
                f"{received} / {agg.expected} maç hazır. "
                "Bazı tahminler henüz tamamlanmadı."
            )
        else:
            answer_text = f"{received} maç tahmini hazır."

        multiple_versions = len(calibration_groups) > 1
        mismatch_policy = cfg.nlp_summary_calibration_mismatch_policy
        if multiple_versions and mismatch_policy == "refuse":
            degraded = True
            degraded_reasons.append("summary calibration mismatch")
            links = ", ".join(sorted(set(prediction_links)))
            answer_text = (
                "Bu hafta için tahminler farklı kalibrasyon sürümleriyle üretildiği için "
                "birleşik özet sunulamıyor."
            )
            if links:
                answer_text += f" Maç bağlantıları: {links}"
        elif multiple_versions and mismatch_policy == "note":
            answer_text += (
                " Not: Bu özet farklı kalibrasyon sürümleri içeren tahminleri birlikte sunar."
            )
        
        # Compute degraded_reason: join non-empty reasons or None if list is empty
        combined_reason = "; ".join(degraded_reasons) if degraded_reasons else None
        
        # Build citations: one entry per unique calibration_version.
        # If multiple versions exist, add explicit Turkish note to each.
        citations = []
        for cal_ver in sorted(calibration_groups.keys()):
            count = calibration_groups[cal_ver]
            entry: dict = {
                "calibration_version": cal_ver,
                "prediction_count": count,
            }
            if multiple_versions:
                entry["note"] = f"{count} tahmin için kalibrasyon güncellendi"
            citations.append(entry)
        
        return Message.new(
            topic=QA_ANSWER_V1,
            payload={
                "request_id": agg.qa_request_id,
                # §10.6 invariant: use the dispatch qa_correlation_id that was
                # carried through predict.approved.v1, not the raw summary_corr
                # key (they may differ once Phase 5 additive field is live).
                "qa_correlation_id": agg.qa_correlation_id,
                "intent": "summary",
                "answer_text": answer_text,
                "kind": "summary",
                "degraded": degraded,
                "degraded_reason": combined_reason,
                "citations": citations,
                "emitted_at": self._clock_iso(),
            },
            producer=self.name,
        )


class NlpProofreaderAgent:
    """Phase 10 §10.9 skeleton: PII detection + post-block clean path.

    Subscribes to ``qa.answer.v1`` (assembled answer from
    ``nlp.answer.v1``); runs PII detection and, when redaction is
    needed, republishes to ``qa.answer.v1`` (clean path) and emits
    ``nlp.event.v1{kind=pii_in_answer_redacted}`` /
    ``nlp.alert.v1`` for operator visibility.
    """

    name = "nlp.proofreader.v1"
    subscribes = [QA_ANSWER_V1]
    publishes = [QA_ANSWER_V1, NLP_EVENT_V1, NLP_ALERT_V1]

    def __init__(
        self,
        monotonic: Callable[[], float] | None = None,
        deduper: object | None = None,
    ) -> None:
        self._log = logging.getLogger("swarm.agents.nlp.proofreader")
        add_log_filter(self._log, filters=(PIIScrubFilter(),))
        self._monotonic = monotonic or _time.monotonic
        _enforce_nlp_spool_audit_dir_modes()
        # §10.13 producer-side deduper (lazy-init from cfg).
        self._deduper = deduper
        self._deduper_lock = _threading.Lock()

    def _get_deduper(self) -> object:
        """Return the proofreader deduper, lazily creating it from cfg."""
        if self._deduper is None:
            with self._deduper_lock:
                if self._deduper is None:
                    from common.config import cfg
                    from swarm.sdk import RequestIdDeduper
                    self._deduper = RequestIdDeduper(
                        window_s=float(cfg.nlp_request_dedup_window_s),
                        max_keys=_NLP_DEDUP_MAX_KEYS,
                        clock=self._monotonic,
                    )
        return self._deduper

    def handle(self, msg: Message) -> Iterable[Message]:
        """Process qa.answer.v1 (stub for §10.9).

        §10.13 idempotency: dedup on request_id at ingress.
        """
        request_id = str(msg.payload.get("request_id", ""))
        if self._get_deduper().seen(request_id):  # type: ignore[union-attr]
            return []
        # Stub: full implementation lands in §10.9 bullets.
        return []


__all__ = [
    "NlpAnswerAgent",
    "NlpBusCircuitBreaker",
    "NlpDispatcherAgent",
    "NlpIntentAgent",
    "NlpProofreaderAgent",
]
