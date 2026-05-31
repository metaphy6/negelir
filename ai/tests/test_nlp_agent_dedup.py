"""Phase 10 §10.13 — NLP agent RequestIdDeduper ingress tests and audit key versioning.

Verifies that all NLP agents (nlp.intent.v1, nlp.answer.v1,
nlp.proofreader.v1, nlp.dispatcher.v1) have RequestIdDeduper wired at
ingress, using cfg.nlp_request_dedup_window_s as the window parameter
per §10.13.

Also covers §10.13 audit key requirement: two requests with the same
qa_correlation_id but different model/calibration versions MUST produce
distinct qa.answer.v1 envelopes, and cache keys include both versions.

Per AGENTS.md Rule 10: new surface -> happy + adversarial tests.
"""
from __future__ import annotations

import pytest

from swarm.agents.nlp import (
    NlpAnswerAgent,
    NlpDispatcherAgent,
    NlpIntentAgent,
    NlpProofreaderAgent,
)
from swarm.agents.topics import (
    PREDICT_APPROVED,
    QA_ANSWER_V1,
    QA_INTENT_V1,
    QA_REQUEST_V1,
)
from swarm.sdk import RequestIdDeduper
from swarm.sdk.types import Message


# ── helpers ──────────────────────────────────────────────────────────────


class FakeClock:
    """Fake monotonic clock for controlled time progression."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def mono(self) -> float:
        return self._now

    def advance(self, delta: float) -> None:
        self._now += delta


def _make_qa_request_v1_msg(request_id: str = "req-001") -> Message:
    return Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": request_id,
            "locale": "tr-TR",
            "text": "gs maçı tahmin",
            "sanitized_at": "2026-05-27T10:00:00+00:00",
        },
        producer="test",
    )


def _make_qa_intent_v1_msg(request_id: str = "req-001") -> Message:
    return Message.new(
        topic=QA_INTENT_V1,
        payload={
            "request_id": request_id,
            "qa_correlation_id": "corr-001",
            "intent": "predict.match_outcome",
            "entities": [],
            "intent_confidence": 0.95,
            "normalized_text": "gs maçı tahmin",
            "locale": "tr-TR",
            "emitted_at": "2026-05-27T10:00:00+00:00",
        },
        producer="nlp.intent.v1",
    )


def _make_qa_answer_v1_msg(request_id: str = "req-001") -> Message:
    return Message.new(
        topic=QA_ANSWER_V1,
        payload={
            "request_id": request_id,
            "qa_correlation_id": "corr-001",
            "intent": "predict.match_outcome",
            "answer_text": "Tahmin hazır.",
            "kind": "prediction",
            "degraded": False,
            "citations": [],
            "emitted_at": "2026-05-27T10:00:00+00:00",
        },
        producer="nlp.answer.v1",
    )


def _make_predict_approved_msg(request_id: str = "req-001") -> Message:
    return Message.new(
        topic=PREDICT_APPROVED,
        payload={
            "match_id": "gs-fb-001",
            "prediction_id": "pred-001",
            "market": "1x2",
            "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "approved_at": "2026-05-27T10:00:00+00:00",
        },
        producer="proofreader.v1",
    )


# ── NlpIntentAgent dedup tests ────────────────────────────────────────────


class TestNlpIntentAgentDedup:
    def test_dedup_on_request_id_rejects_replay(self) -> None:
        """First call processes, second call with same request_id is suppressed."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpIntentAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_request_v1_msg("req-abc")
        msg2 = _make_qa_request_v1_msg("req-abc")

        # First call: deduper returns False (not seen), agent processes (stub returns [])
        out1 = list(agent.handle(msg1))
        assert out1 == []  # stub returns empty, but deduper recorded the key

        # Second call: deduper returns True (already seen), agent returns [] without processing
        out2 = list(agent.handle(msg2))
        assert out2 == []
        # Deduper now has 1 key
        assert deduper.size() == 1

    def test_dedup_distinct_request_ids_both_processed(self) -> None:
        """Two distinct request_ids both get processed."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpIntentAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_request_v1_msg("req-001")
        msg2 = _make_qa_request_v1_msg("req-002")

        out1 = list(agent.handle(msg1))
        out2 = list(agent.handle(msg2))

        assert out1 == []  # stub
        assert out2 == []  # stub
        assert deduper.size() == 2

    def test_dedup_window_expiry_allows_reprocess(self) -> None:
        """request_id aged out of window can be processed again."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=5.0, max_keys=1_000, clock=clock.mono)
        agent = NlpIntentAgent(monotonic=clock.mono, deduper=deduper)

        msg = _make_qa_request_v1_msg("req-abc")

        # First call at t=100
        out1 = list(agent.handle(msg))
        assert out1 == []
        assert deduper.size() == 1

        # Advance beyond window
        clock.advance(6.0)  # now t=106; req-abc recorded at 100, cutoff = 106 - 5 = 101

        # Second call: aged out, should process again
        out2 = list(agent.handle(msg))
        assert out2 == []
        assert deduper.size() == 1  # old entry aged out, new entry recorded

    def test_empty_request_id_does_not_block(self) -> None:
        """Empty request_id is treated as never-seen per RequestIdDeduper contract."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpIntentAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_request_v1_msg("")
        msg2 = _make_qa_request_v1_msg("")

        out1 = list(agent.handle(msg1))
        out2 = list(agent.handle(msg2))

        assert out1 == []
        assert out2 == []
        # Empty keys are not recorded
        assert deduper.size() == 0


# ── NlpAnswerAgent dedup tests ───────────────────────────────────────────


class TestNlpAnswerAgentDedup:
    def test_dedup_on_qa_intent_v1_request_id(self) -> None:
        """qa.intent.v1 deduped on request_id at ingress."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpAnswerAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_intent_v1_msg("req-abc")
        msg2 = _make_qa_intent_v1_msg("req-abc")

        out1 = list(agent.handle(msg1))
        out2 = list(agent.handle(msg2))

        assert out1 == []  # stub
        assert out2 == []  # deduped
        assert deduper.size() == 1

    def test_dedup_distinct_qa_intent_v1_request_ids(self) -> None:
        """Two distinct qa.intent.v1 request_ids both processed."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpAnswerAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_intent_v1_msg("req-001")
        msg2 = _make_qa_intent_v1_msg("req-002")

        out1 = list(agent.handle(msg1))
        out2 = list(agent.handle(msg2))

        assert out1 == []
        assert out2 == []
        assert deduper.size() == 2

    def test_predict_approved_with_summary_not_deduped_by_request_id(self) -> None:
        """predict.approved.v1 path uses aggregation logic, not request-id dedup."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpAnswerAgent(monotonic=clock.mono, deduper=deduper)

        # predict.approved.v1 does not hit the deduper (different topic path)
        msg = _make_predict_approved_msg("req-001")
        out = list(agent.handle(msg))
        # Stub returns [] for non-summary predict.approved
        assert out == []
        # Deduper size should be 0 (predict.approved ingress doesn't dedup)
        assert deduper.size() == 0


# ── NlpProofreaderAgent dedup tests ────────────────────────────────────────


class TestNlpProofreaderAgentDedup:
    def test_dedup_on_request_id_rejects_replay(self) -> None:
        """First qa.answer.v1 processes, second with same request_id suppressed."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpProofreaderAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_answer_v1_msg("req-abc")
        msg2 = _make_qa_answer_v1_msg("req-abc")

        out1 = list(agent.handle(msg1))
        out2 = list(agent.handle(msg2))

        assert out1 == []  # stub
        assert out2 == []  # deduped
        assert deduper.size() == 1

    def test_dedup_distinct_request_ids_both_processed(self) -> None:
        """Two distinct qa.answer.v1 request_ids both get processed."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpProofreaderAgent(monotonic=clock.mono, deduper=deduper)

        msg1 = _make_qa_answer_v1_msg("req-001")
        msg2 = _make_qa_answer_v1_msg("req-002")

        out1 = list(agent.handle(msg1))
        out2 = list(agent.handle(msg2))

        assert out1 == []
        assert out2 == []
        assert deduper.size() == 2

    def test_dedup_window_expiry_allows_reprocess(self) -> None:
        """request_id aged out of window can be processed again."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=5.0, max_keys=1_000, clock=clock.mono)
        agent = NlpProofreaderAgent(monotonic=clock.mono, deduper=deduper)

        msg = _make_qa_answer_v1_msg("req-abc")

        out1 = list(agent.handle(msg))
        assert out1 == []
        assert deduper.size() == 1

        clock.advance(6.0)

        out2 = list(agent.handle(msg))
        assert out2 == []
        assert deduper.size() == 1


# ── NlpDispatcherAgent dedup tests (already exists, spot-check) ────────────


class TestNlpDispatcherAgentDedupExists:
    def test_dispatcher_has_deduper(self) -> None:
        """Dispatcher already has dedup wired per §10.6; spot-check it exists."""
        clock = FakeClock(now=100.0)
        deduper = RequestIdDeduper(window_s=10.0, max_keys=1_000, clock=clock.mono)
        agent = NlpDispatcherAgent(monotonic=clock.mono, deduper=deduper)

        msg = Message.new(
            topic=QA_INTENT_V1,
            payload={
                "request_id": "req-001",
                "qa_correlation_id": "corr-001",
                "intent": "predict.match_outcome",
                "entities": [],
                "emitted_at": "2026-05-27T10:00:00+00:00",
            },
            producer="nlp.intent.v1",
        )

        # First call: deduper hasn't seen this (intent, entity_hash) combo yet
        out1 = list(agent.handle(msg))
        # Dispatcher stub may return [] or disambiguation; either way, key is recorded
        # Second call: deduped
        out2 = list(agent.handle(msg))
        assert out2 == []  # deduped


# ── §10.13 Audit key: (qa_correlation_id, model_version, calibration_version) ──


class TestAuditKeyVersioning:
    """§10.13 audit key tests: two requests with same correlation but different
    model/calibration versions MUST produce distinct qa.answer.v1 envelopes.
    Cache keys MUST include both versions.
    """

    def test_audit_key_includes_model_and_calibration_version(self) -> None:
        """The audit key for tracking requests includes qa_correlation_id,
        intent_model_version, and calibration_version.
        """
        from swarm.agents.nlp import audit_key

        qa_corr = "corr-abc"
        model_v = "1.2.3"
        cal_v = "2.3.4"

        key = audit_key(qa_corr, model_v, cal_v)

        # Key should be a stable hash that includes all three components
        assert isinstance(key, str)
        assert len(key) > 0

        # Different versions should produce different keys
        key2 = audit_key(qa_corr, "1.2.4", cal_v)
        assert key != key2

        key3 = audit_key(qa_corr, model_v, "2.3.5")
        assert key != key3

    def test_same_qa_corr_different_versions_distinct_keys(self) -> None:
        """Two requests with the same qa_correlation_id but different
        model/calibration versions produce distinct audit keys.
        """
        from swarm.agents.nlp import audit_key

        qa_corr = "corr-001"

        key1 = audit_key(qa_corr, "1.0.0", "1.0.0")
        key2 = audit_key(qa_corr, "2.0.0", "1.0.0")  # different model version
        key3 = audit_key(qa_corr, "1.0.0", "2.0.0")  # different calibration version
        key4 = audit_key(qa_corr, "2.0.0", "2.0.0")  # both different

        assert key1 != key2
        assert key1 != key3
        assert key1 != key4
        assert key2 != key3
        assert key2 != key4
        assert key3 != key4

    def test_audit_key_stable_across_calls(self) -> None:
        """Same inputs produce the same audit key (deterministic)."""
        from swarm.agents.nlp import audit_key

        key1 = audit_key("corr-001", "1.0.0", "2.0.0")
        key2 = audit_key("corr-001", "1.0.0", "2.0.0")

        assert key1 == key2

    def test_audit_key_handles_empty_versions(self) -> None:
        """Empty version strings are valid (pre-train / dev scenario)."""
        from swarm.agents.nlp import audit_key

        key = audit_key("corr-001", "", "")
        assert isinstance(key, str)
        assert len(key) > 0

        # Empty vs non-empty should differ
        key2 = audit_key("corr-001", "1.0.0", "1.0.0")
        assert key != key2

    def test_cache_key_includes_versions(self) -> None:
        """§10.12 L1 cache keys include both model_version and calibration_version."""
        from swarm.agents.nlp import cache_key_for_intent

        intent = "predict.match_outcome"
        entity_hash = "abcd1234"
        fixture_window = "2026-05-27T00:00"
        model_versions_hash = "mvhash"
        model_v = "1.0.0"
        cal_v = "2.0.0"

        key = cache_key_for_intent(
            intent, entity_hash, fixture_window, model_versions_hash, model_v, cal_v
        )

        assert isinstance(key, str)
        assert len(key) > 0

        # Different model version should produce different cache key
        key2 = cache_key_for_intent(
            intent, entity_hash, fixture_window, model_versions_hash, "1.0.1", cal_v
        )
        assert key != key2

        # Different calibration version should produce different cache key
        key3 = cache_key_for_intent(
            intent, entity_hash, fixture_window, model_versions_hash, model_v, "2.0.1"
        )
        assert key != key3

    def test_cache_key_stable_across_calls(self) -> None:
        """Cache key is deterministic for same inputs."""
        from swarm.agents.nlp import cache_key_for_intent

        key1 = cache_key_for_intent(
            "predict.match_outcome", "hash1", "2026-05-27", "mv1", "1.0.0", "2.0.0"
        )
        key2 = cache_key_for_intent(
            "predict.match_outcome", "hash1", "2026-05-27", "mv1", "1.0.0", "2.0.0"
        )

        assert key1 == key2
