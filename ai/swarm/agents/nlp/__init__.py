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
import threading as _threading
import time as _time
from typing import Callable, Iterable
from uuid import uuid4

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

# ── internal helpers ──────────────────────────────────────────────────────

# Entity kinds that can anchor a predict.* intent to a specific fixture.
_FIXTURE_ENTITY_KINDS = frozenset({"team", "competition"})

# Summary intents that fan-out to multiple predict.request.v1 messages.
_SUMMARY_INTENTS = frozenset({"summary.next_week", "summary.matchday"})

# Maximum number of dedup keys held in each NLP agent's LRU (structural cap;
# not a config knob because it is a data-structure bound, not a tunable
# threshold — the window_s config is the user-facing knob).
_NLP_DEDUP_MAX_KEYS: int = 100_000


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
        self._monotonic = monotonic or _time.monotonic
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
        self._clock_iso = clock_iso or _utc_iso
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
                    "tier_id_required": None,
                    "citations": [],
                    "emitted_at": self._clock_iso(),
                },
                producer=self.name,
            )
        ]

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
        self._clock_iso = clock_iso or _utc_iso
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
        import re

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

        # PII redaction: simple regex for email and phone patterns.
        redacted_text = answer_text
        # Email: basic pattern
        redacted_text = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "[REDACTED_EMAIL]",
            redacted_text,
        )
        # Phone: Turkish mobile pattern (05XX XXX XX XX, with optional spaces/dashes)
        redacted_text = re.sub(
            r"\b0[5-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b",
            "[REDACTED_PHONE]",
            redacted_text,
        )

        # Prepare audit payload.
        audit_payload = {
            "qa_correlation_id": qa_correlation_id,
            "answer_text_redacted": redacted_text,
            "envelope": envelope,
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
        summary_corr = payload.get("summary_correlation_id")
        if summary_corr:
            return self._on_summary_prediction_arrived(payload, str(summary_corr))
        # Single-predict path: stub for future §10.7 bullets.
        return []

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
        
        # Compute degraded_reason: join non-empty reasons or None if list is empty
        combined_reason = "; ".join(degraded_reasons) if degraded_reasons else None
        
        # Build citations: one entry per unique calibration_version.
        # If multiple versions exist, add explicit Turkish note to each.
        citations = []
        multiple_versions = len(calibration_groups) > 1
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
        self._monotonic = monotonic or _time.monotonic
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
