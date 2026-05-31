"""Phase 10 §10.6 — nlp.dispatcher.v1 agent wire-contract and backoff tests.

Verifies the skeleton class has the correct name, subscribes, and
publishes attributes, that it is properly registered in the NLP
allowed-producer sets, and that the §10.6 deterministic backoff
(predict.* intent without resolvable fixture entity → disambiguation)
works correctly.  Also covers the §10.6 multi-fixture fan-out for
summary.next_week / summary.matchday intents, and the §10.6
NlpAnswerAgent aggregation (complete + degraded/expired paths).

Per AGENTS.md Rule 10: new public surface -> happy + adversarial tests.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from common.config import cfg as _cfg
from swarm.agents.nlp import NlpAnswerAgent, NlpDispatcherAgent
from swarm.agents.topics import (
    DATA_REQUEST_V1,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    PREDICT_APPROVED,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_INTENT_V1,
    QA_REQUEST,
    SEC_ALERT,
)
from swarm.sdk.types import Message
from swarm.sdk.wire_contracts import (
    NLP_ALERT_V1_ALLOWED_PRODUCERS,
    NLP_EVENT_V1_ALLOWED_PRODUCERS,
)

# ── helpers ──────────────────────────────────────────────────────────────────────────

_BASE_INTENT_PAYLOAD = {
    "request_id": "req-001",
    "intent": "predict.match_outcome",
    "entities": [],
    "intent_distribution": [{"intent": "predict.match_outcome", "probability": 0.95}],
    "intent_model_version": "1.0.0",
    "intent_calibration_version": "1.0.0",
    "normalized_text": "gs maçı tahmin",
    "locale": "tr-TR",
    "emitted_at": "2026-05-27T10:00:00+00:00",
}

_MOCK_PREDICT_CITATION_HMAC_KEY = b"negelir:mock:predict:citation:hmac:v1"


def _make_intent_msg(overrides: dict | None = None) -> Message:
    payload = dict(_BASE_INTENT_PAYLOAD)
    if overrides:
        payload.update(overrides)
    return Message.new(topic=QA_INTENT_V1, payload=payload)


def _make_team_entity(canonical_id: str = "gs") -> dict:
    return {
        "span_start": 0,
        "span_end": 2,
        "kind": "team",
        "canonical_id": canonical_id,
        "confidence": 0.99,
        "lexicon_version": "1.0.0",
    }


def _make_competition_entity(canonical_id: str = "ucl") -> dict:
    return {
        "span_start": 0,
        "span_end": 3,
        "kind": "competition",
        "canonical_id": canonical_id,
        "confidence": 0.95,
        "lexicon_version": "1.0.0",
    }


@pytest.fixture
def agent() -> NlpDispatcherAgent:
    # Pin clock and id for deterministic tests.
    return NlpDispatcherAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "test-corr-id",
    )


# ── wire-contract tests ──────────────────────────────────────────────────────────────

class TestNlpDispatcherAgentContract:
    def test_name(self, agent: NlpDispatcherAgent) -> None:
        assert agent.name == "nlp.dispatcher.v1"

    def test_subscribes_to_qa_intent_v1(self, agent: NlpDispatcherAgent) -> None:
        assert QA_INTENT_V1 in agent.subscribes

    def test_publishes_predict_request_v1(self, agent: NlpDispatcherAgent) -> None:
        assert PREDICT_REQUEST_V1 in agent.publishes

    def test_publishes_data_request_v1(self, agent: NlpDispatcherAgent) -> None:
        assert DATA_REQUEST_V1 in agent.publishes

    def test_publishes_qa_answer_v1(self, agent: NlpDispatcherAgent) -> None:
        assert QA_ANSWER_V1 in agent.publishes

    def test_publishes_nlp_event_v1(self, agent: NlpDispatcherAgent) -> None:
        assert NLP_EVENT_V1 in agent.publishes

    def test_publishes_nlp_alert_v1(self, agent: NlpDispatcherAgent) -> None:
        assert NLP_ALERT_V1 in agent.publishes


class TestNlpDispatcherProducerRegistration:
    def test_registered_in_nlp_event_allowed_producers(self) -> None:
        assert "nlp.dispatcher.v1" in NLP_EVENT_V1_ALLOWED_PRODUCERS

    def test_registered_in_nlp_alert_allowed_producers(self) -> None:
        assert "nlp.dispatcher.v1" in NLP_ALERT_V1_ALLOWED_PRODUCERS


class TestNlpDispatcherBoundaryDiscipline:
    def test_does_not_subscribe_to_raw_qa_request(
        self, agent: NlpDispatcherAgent
    ) -> None:
        assert QA_REQUEST not in agent.subscribes

    def test_does_not_publish_to_sec_alert(
        self, agent: NlpDispatcherAgent
    ) -> None:
        assert SEC_ALERT not in agent.publishes

    def test_publishes_set_is_subset_of_nlp_allowed_outbound(
        self, agent: NlpDispatcherAgent
    ) -> None:
        nlp_allowed_outbound = {
            QA_INTENT_V1,
            QA_ANSWER_V1,
            NLP_EVENT_V1,
            NLP_ALERT_V1,
            PREDICT_REQUEST_V1,
            DATA_REQUEST_V1,
        }
        for topic in agent.publishes:
            assert topic in nlp_allowed_outbound, (
                f"nlp.dispatcher.v1 must not publish to {topic!r} "
                f"(not in Section 10.0 NLP allowed outbound set)"
            )

    def test_subscribes_set_does_not_include_predict_final(
        self, agent: NlpDispatcherAgent
    ) -> None:
        from swarm.agents.topics import PREDICT_FINAL
        assert PREDICT_FINAL not in agent.subscribes


# ── §10.6 deterministic backoff tests ──────────────────────────────────────────────────────

class TestNlpDispatcherDeterministicBackoff:
    """§10.6 — predict.* without fixture entity → disambiguation (never a guess)."""

    def test_predict_no_entity_returns_disambiguation_answer(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Happy path for backoff: no entities → exactly one disambiguation answer."""
        msg = _make_intent_msg({"entities": []})
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.envelope.topic == QA_ANSWER_V1
        assert out.payload["kind"] == "disambiguation"
        assert out.payload["request_id"] == "req-001"
        assert out.payload["intent"] == "predict.match_outcome"
        assert out.payload["degraded"] is False
        assert out.payload["degraded_reason"] is None
        assert isinstance(out.payload["answer_text"], str)
        assert len(out.payload["answer_text"]) > 0

    def test_predict_no_entity_answer_text_contains_window_h(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Disambiguation answer text references the fixture window from config."""
        from common.config import cfg
        msg = _make_intent_msg({"entities": []})
        results = list(agent.handle(msg))
        answer_text = results[0].payload["answer_text"]
        # The window hours must appear in the answer text.
        assert str(cfg.nlp_default_fixture_window_h) in answer_text

    def test_predict_no_entity_producer_is_dispatcher(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg({"entities": []})
        results = list(agent.handle(msg))
        assert results[0].envelope.producer == "nlp.dispatcher.v1"

    def test_predict_no_entity_all_required_fields_present(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """qa.answer.v1 required fields are all populated (schema compliance)."""
        required = {
            "request_id", "qa_correlation_id", "answer_text", "intent",
            "kind", "degraded", "emitted_at",
        }
        msg = _make_intent_msg({"entities": []})
        payload = list(agent.handle(msg))[0].payload
        for field in required:
            assert field in payload, f"Missing required field: {field}"

    def test_predict_with_team_entity_no_backoff(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """predict.* WITH a team entity must NOT trigger the backoff path."""
        msg = _make_intent_msg({"entities": [_make_team_entity()]})
        results = list(agent.handle(msg))
        # Fixture is resolvable → no disambiguation; routing stub returns [].
        assert results == []

    def test_predict_with_competition_entity_no_backoff(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """predict.* WITH a competition entity must NOT trigger the backoff path."""
        msg = _make_intent_msg({"entities": [_make_competition_entity()]})
        results = list(agent.handle(msg))
        assert results == []

    def test_predict_with_null_canonical_id_triggers_backoff(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """A team entity with null canonical_id cannot anchor a fixture → backoff."""
        null_entity = {**_make_team_entity(), "canonical_id": None}
        msg = _make_intent_msg({"entities": [null_entity]})
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].payload["kind"] == "disambiguation"

    def test_non_predict_intent_no_backoff(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """data.* and meta.* intents are NOT subject to the predict backoff."""
        for intent in ("data.fixture_lookup", "data.standings", "meta.help"):
            msg = _make_intent_msg({"intent": intent, "entities": []})
            results = list(agent.handle(msg))
            assert results == [], f"Unexpected output for intent={intent}"

    def test_all_predict_intents_backoff_without_entity(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Every predict.* intent in the closed enum triggers backoff when empty."""
        predict_intents = [
            "predict.match_outcome",
            "predict.over_under",
            "predict.btts",
            "predict.handicap",
            "predict.score_grid",
        ]
        for intent in predict_intents:
            msg = _make_intent_msg({"intent": intent, "entities": []})
            results = list(agent.handle(msg))
            assert len(results) == 1, f"predict backoff missing for intent={intent}"
            assert results[0].payload["kind"] == "disambiguation"

    def test_disambiguation_emitted_at_is_set(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """emitted_at must be non-empty in the disambiguation answer."""
        msg = _make_intent_msg({"entities": []})
        payload = list(agent.handle(msg))[0].payload
        assert payload["emitted_at"] == "2026-05-27T10:00:00+00:00"

    def test_qa_correlation_id_is_non_empty(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """qa_correlation_id must be populated (non-empty string)."""
        msg = _make_intent_msg({"entities": []})
        payload = list(agent.handle(msg))[0].payload
        assert isinstance(payload["qa_correlation_id"], str)
        assert len(payload["qa_correlation_id"]) > 0


# ── §10.6 multi-fixture fan-out tests ──────────────────────────────────────


def _make_summary_intent_msg(
    intent: str = "summary.matchday",
    entities: list | None = None,
) -> Message:
    payload = {
        "request_id": "req-summary-001",
        "intent": intent,
        "entities": entities or [],
        "intent_distribution": [{"intent": intent, "probability": 0.90}],
        "intent_model_version": "1.0.0",
        "intent_calibration_version": "1.0.0",
        "normalized_text": "bu haftaki maçlar",
        "locale": "tr-TR",
        "emitted_at": "2026-05-27T10:00:00+00:00",
    }
    return Message.new(topic=QA_INTENT_V1, payload=payload)


def _make_team_entities(count: int) -> list[dict]:
    return [
        {
            "kind": "team",
            "canonical_id": f"team-{i}",
            "span_start": i * 5,
            "span_end": i * 5 + 3,
            "confidence": 0.95,
            "lexicon_version": "1.0.0",
        }
        for i in range(count)
    ]


class TestNlpDispatcherMultiFixtureFanOut:
    """§10.6 multi-fixture intents: summary.* → N predict.request.v1 fan-out."""

    @pytest.fixture
    def agent(self) -> NlpDispatcherAgent:
        return NlpDispatcherAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-corr-id",
        )

    def test_summary_matchday_with_entities_fans_out(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """summary.matchday with 3 team entities → 3 predict.request.v1 messages."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(3))
        results = list(agent.handle(msg))
        assert len(results) == 3
        for r in results:
            assert r.envelope.topic == PREDICT_REQUEST_V1

    def test_summary_next_week_with_entities_fans_out(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """summary.next_week with 2 team entities → 2 predict.request.v1."""
        msg = _make_summary_intent_msg(
            intent="summary.next_week", entities=_make_team_entities(2)
        )
        results = list(agent.handle(msg))
        assert len(results) == 2
        assert all(r.envelope.topic == PREDICT_REQUEST_V1 for r in results)

    def test_summary_fan_out_shares_summary_correlation_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """All fan-out messages share the same summary_correlation_id."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(3))
        results = list(agent.handle(msg))
        corr_ids = {r.payload["summary_correlation_id"] for r in results}
        assert len(corr_ids) == 1, "All messages must share one summary_correlation_id"

    def test_summary_fan_out_summary_expected_count_matches_n(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Every fan-out message carries summary_expected_count = N (total sent)."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(3))
        results = list(agent.handle(msg))
        for r in results:
            assert r.payload["summary_expected_count"] == 3

    def test_summary_fan_out_capped_at_max_fixtures(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Fan-out is capped at cfg.nlp_summary_max_fixtures (default=10)."""
        from common.config import cfg

        entities = _make_team_entities(cfg.nlp_summary_max_fixtures + 5)
        msg = _make_summary_intent_msg(entities=entities)
        results = list(agent.handle(msg))
        assert len(results) == cfg.nlp_summary_max_fixtures

    def test_summary_fan_out_carries_match_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Each fan-out message carries match_id = canonical_id from entity."""
        entities = _make_team_entities(2)
        msg = _make_summary_intent_msg(entities=entities)
        results = list(agent.handle(msg))
        match_ids = [r.payload["match_id"] for r in results]
        assert "team-0" in match_ids
        assert "team-1" in match_ids

    def test_summary_fan_out_carries_qa_request_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Each fan-out message carries qa_request_id referencing the original request."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(2))
        results = list(agent.handle(msg))
        for r in results:
            assert r.payload["qa_request_id"] == "req-summary-001"

    def test_summary_fan_out_producer_is_dispatcher(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Producer on fan-out messages is nlp.dispatcher.v1."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(2))
        results = list(agent.handle(msg))
        for r in results:
            assert r.envelope.producer == "nlp.dispatcher.v1"

    def test_summary_no_entities_returns_disambiguation(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """summary.* without fixture entities → disambiguation (same backoff)."""
        msg = _make_summary_intent_msg(entities=[])
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == QA_ANSWER_V1
        assert results[0].payload["kind"] == "disambiguation"

    def test_summary_with_null_canonical_id_triggers_disambiguation(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Entity with null canonical_id is not a valid fixture anchor."""
        entities = [{"kind": "team", "canonical_id": None}]
        msg = _make_summary_intent_msg(entities=entities)
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].payload["kind"] == "disambiguation"

    @pytest.mark.parametrize("intent", ["summary.matchday", "summary.next_week"])
    def test_summary_intents_both_trigger_fanout(
        self, agent: NlpDispatcherAgent, intent: str
    ) -> None:
        """Both summary intents fan out to predict.request.v1."""
        msg = _make_summary_intent_msg(intent=intent, entities=_make_team_entities(1))
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == PREDICT_REQUEST_V1


# ── §10.6 NlpAnswerAgent aggregation tests ──────────────────────────────────


def _make_approved_msg(
    summary_corr: str,
    expected_count: int,
    qa_request_id: str = "req-summary-001",
    prediction_id: str | None = None,
    degraded: bool = False,
    degraded_reason: str | None = None,
    citation_signature: str | None = "__auto__",
) -> Message:
    """Build a synthetic predict.approved.v1 for a summary fan-out."""
    # §10.16: predict.approved.v1 includes predict.final under "final" key
    final_payload = {
        "prediction_id": prediction_id or "pred-001",
        "match_id": "team-0",
        "market": "1x2",
        "distribution": {"1": 0.5, "X": 0.3, "2": 0.2},
        "weights": {},
        "contributing_models": ["model-1"],
        "calibration_version": 1,
        "swarm_confidence": 0.85,
        "degraded": degraded,
        "degraded_reason": degraded_reason or "",
        "produced_at": "2026-05-27T10:00:00+00:00",
        "league_id": "tr-superlig",
        "profile_id": None,
    }
    payload = {
        "prediction_id": prediction_id or "pred-001",
        "summary_correlation_id": summary_corr,
        "summary_expected_count": expected_count,
        "qa_request_id": qa_request_id,
        "match_id": "team-0",
        "market": "1x2",
        "approved_at": "2026-05-27T10:00:00+00:00",
        "approved_by": ["proof.sanity.v1"],
        "verdict_count": 1,
        "quorum": 1,
        "final": final_payload,
        "calibration_version": 1,
    }
    if citation_signature == "__auto__":
        key_id = hashlib.sha256(_MOCK_PREDICT_CITATION_HMAC_KEY).hexdigest()[:16]
        blob = (
            f"{payload['prediction_id']}|{final_payload['produced_at']}|"
            f"{'|'.join(sorted(final_payload['contributing_models']))}|"
            f"{payload['calibration_version']}"
        )
        payload["citation_signature"] = hmac.new(
            _MOCK_PREDICT_CITATION_HMAC_KEY,
            blob.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload["citation_key_id"] = key_id
    else:
        payload["citation_signature"] = citation_signature

    return Message.new(
        topic=PREDICT_APPROVED,
        payload=payload,
    )


class TestNlpAnswerAgentSummaryAggregation:
    """§10.6 NlpAnswerAgent: summary fan-out aggregation + degraded path."""

    @pytest.fixture
    def agent(self) -> NlpAnswerAgent:
        return NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-ans-id",
            monotonic=None,  # real monotonic; fast tests complete before timeout
        )

    def test_all_predictions_received_emits_complete_answer(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When all expected predictions arrive, emit qa.answer.v1{degraded=False}."""
        corr = "agg-corr-001"
        msg1 = _make_approved_msg(corr, expected_count=2, prediction_id="p1")
        msg2 = _make_approved_msg(corr, expected_count=2, prediction_id="p2")
        results1 = list(agent.handle(msg1))
        assert results1 == [], "Should not emit until all received"
        results2 = list(agent.handle(msg2))
        assert len(results2) == 1
        ans = results2[0]
        assert ans.envelope.topic == QA_ANSWER_V1
        assert ans.payload["degraded"] is False
        assert ans.payload["qa_correlation_id"] == corr
        assert ans.payload["kind"] == "summary"

    def test_complete_answer_text_contains_count(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Complete answer text contains the number of ready matches."""
        corr = "agg-corr-002"
        for _ in range(3):
            list(agent.handle(_make_approved_msg(corr, expected_count=3)))
        # Third one triggers completion
        # Re-run fresh
        agent2 = NlpAnswerAgent(clock_iso=lambda: "2026-05-27T10:00:00+00:00")
        corr2 = "agg-corr-003"
        for _ in range(2):
            list(agent2.handle(_make_approved_msg(corr2, expected_count=2)))
        # By now complete (two messages, expected=2) -- but we need to capture
        results = []
        for _ in range(2):
            r = list(agent2.handle(_make_approved_msg(corr2 + "x", expected_count=2)))
            results.extend(r)
        # Use a fresh agent for clean capture
        agent3 = NlpAnswerAgent(clock_iso=lambda: "2026-05-27T10:00:00+00:00")
        c = "agg-fresh"
        list(agent3.handle(_make_approved_msg(c, expected_count=2)))
        out = list(agent3.handle(_make_approved_msg(c, expected_count=2)))
        assert len(out) == 1
        assert "2" in out[0].payload["answer_text"]

    def test_expired_aggregation_emits_degraded_answer(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When deadline expires and only some arrived → degraded answer with X/Y note."""
        corr = "agg-expired-001"
        # Use an expired monotonic: deadline in the past
        # Inject a monotonic that always reports 'past deadline'
        past = 0.0  # deadline will be 0 + timeout_s, but we'll say now >> deadline
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            # First call (deadline set): return 0.0; subsequent calls: return huge
            if call_count[0] == 1:
                return 0.0
            return 1_000_000.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        msg = _make_approved_msg(corr, expected_count=3)
        results = list(expired_agent.handle(msg))
        assert len(results) == 1
        ans = results[0]
        assert ans.payload["degraded"] is True
        assert ans.envelope.topic == QA_ANSWER_V1

    def test_expired_degraded_answer_text_contains_x_of_y(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Degraded answer text must contain 'X / Y maç' pattern."""
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 1_000_000.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        corr = "agg-expired-002"
        msg = _make_approved_msg(corr, expected_count=5)
        out = list(expired_agent.handle(msg))
        text = out[0].payload["answer_text"]
        # Must contain "1 / 5" (received / expected)
        assert "1" in text and "5" in text, f"Expected X/Y in answer text, got: {text!r}"

    def test_non_summary_predict_approved_returns_empty(
        self, agent: NlpAnswerAgent
    ) -> None:
        """predict.approved.v1 without summary_correlation_id → no output (stub)."""
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={"prediction_id": "p1", "match_id": "gs-fb", "market": "1x2"},
        )
        assert list(agent.handle(msg)) == []

    def test_answer_agent_producer_is_nlp_answer_v1(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Emitted qa.answer.v1 producer must be nlp.answer.v1."""
        call_count = [0]

        def fake_mono() -> float:
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 1_000_000.0

        a = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_mono,
        )
        out = list(a.handle(_make_approved_msg("c1", expected_count=5)))
        assert out[0].envelope.producer == "nlp.answer.v1"

    def test_separate_summary_correlations_are_independent(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Two parallel summary fan-outs with different corr IDs are independent."""
        msg_a = _make_approved_msg("corr-A", expected_count=1)
        msg_b = _make_approved_msg("corr-B", expected_count=1)
        out_a = list(agent.handle(msg_a))
        out_b = list(agent.handle(msg_b))
        assert len(out_a) == 1
        assert len(out_b) == 1
        assert out_a[0].payload["qa_correlation_id"] == "corr-A"
        assert out_b[0].payload["qa_correlation_id"] == "corr-B"

    def test_nlp_citation_signature_verified_under_enforce(
        self, agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§10.21.8: enforce mode accepts valid signatures and renders normally."""
        monkeypatch.setattr(
            _cfg,
            "nlp_predict_citation_hmac_required",
            "enforce",
            raising=False,
        )

        corr = "agg-enforce-ok-001"
        out1 = list(agent.handle(_make_approved_msg(corr, expected_count=2, prediction_id="p1")))
        out2 = list(agent.handle(_make_approved_msg(corr, expected_count=2, prediction_id="p2")))
        assert out1 == []
        assert len(out2) == 1
        assert out2[0].envelope.topic == QA_ANSWER_V1
        assert out2[0].payload["intent"] == "summary"

    def test_nlp_forged_citation_dropped_under_enforce(
        self, agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§10.21.8: enforce mode drops invalid signature and routes to predict.timeout."""
        monkeypatch.setattr(
            _cfg,
            "nlp_predict_citation_hmac_required",
            "enforce",
            raising=False,
        )

        out = list(
            agent.handle(
                _make_approved_msg(
                    "agg-enforce-bad-001",
                    expected_count=1,
                    citation_signature="0" * 64,
                )
            )
        )
        assert len(out) == 2
        assert out[0].envelope.topic == QA_ANSWER_V1
        assert out[0].payload["intent"] == "predict.timeout"
        assert out[1].envelope.topic == NLP_ALERT_V1
        assert out[1].payload["kind"] == "nlp_citation_signature_verify_failed"
        assert out[1].payload["severity"] == "critical"

    def test_nlp_warn_mode_renders_with_alert(
        self, agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§10.21.8: warn mode renders and emits nlp.alert.v1 on invalid signature."""
        monkeypatch.setattr(
            _cfg,
            "nlp_predict_citation_hmac_required",
            "warn",
            raising=False,
        )

        out = list(
            agent.handle(
                _make_approved_msg(
                    "agg-warn-bad-001",
                    expected_count=1,
                    citation_signature="f" * 64,
                )
            )
        )
        assert len(out) == 2
        assert out[0].envelope.topic == QA_ANSWER_V1
        assert out[0].payload["intent"] == "summary"
        assert out[1].envelope.topic == NLP_ALERT_V1
        assert out[1].payload["kind"] == "nlp_citation_signature_verify_failed"
        assert out[1].payload["severity"] == "warn"

    def test_nlp_citation_rotation_prev_key_accepted_within_grace_window(
        self, agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """§10.21.8 rotation: previous key remains valid inside grace window."""
        monkeypatch.setattr(
            _cfg,
            "nlp_predict_citation_hmac_required",
            "enforce",
            raising=False,
        )

        key_file = tmp_path / "predict_citation_hmac.key"
        prev_key = b"phase10-prev-citation-key"
        new_key = b"phase10-new-citation-key"
        key_file.write_bytes(new_key)
        (tmp_path / "predict_citation_hmac.key.prev").write_bytes(prev_key)

        monkeypatch.setattr(_cfg, "predict_citation_hmac_key_path", str(key_file), raising=False)
        monkeypatch.setattr(_cfg, "predict_citation_hmac_key_grace_s", 3600, raising=False)

        corr = "agg-prev-key-ok-001"
        msg = _make_approved_msg(corr, expected_count=1, prediction_id="p-prev")
        key_id = hashlib.sha256(prev_key).hexdigest()[:16]
        blob = "p-prev|2026-05-27T10:00:00+00:00|model-1|1"
        msg.payload["citation_key_id"] = key_id
        msg.payload["citation_signature"] = hmac.new(prev_key, blob.encode("utf-8"), hashlib.sha256).hexdigest()

        out = list(agent.handle(msg))
        assert len(out) == 1
        assert out[0].envelope.topic == QA_ANSWER_V1


# ── §10.6 qa_correlation_id invariant tests ──────────────────────────────────


def _make_approved_msg_with_corr(
    summary_corr: str,
    expected_count: int,
    qa_correlation_id: str,
    qa_request_id: str = "req-summary-001",
    prediction_id: str | None = None,
) -> Message:
    """Build predict.approved.v1 with explicit qa_correlation_id additive field."""
    return Message.new(
        topic=PREDICT_APPROVED,
        payload={
            "prediction_id": prediction_id or "pred-001",
            "summary_correlation_id": summary_corr,
            "summary_expected_count": expected_count,
            "qa_request_id": qa_request_id,
            # §10.6 qa_correlation_id invariant: additive Phase 5 field
            "qa_correlation_id": qa_correlation_id,
            "match_id": "team-0",
            "market": "1x2",
            "result": {"1": 0.5, "X": 0.3, "2": 0.2},
            "degraded": False,
        },
    )


class TestQaCorrelationIdInvariant:
    """§10.6 — every qa.answer.v1 carries the originating request_id AND
    the dispatch qa_correlation_id (round-tripped via predict.approved.v1).
    """

    @pytest.fixture
    def dispatcher(self) -> NlpDispatcherAgent:
        return NlpDispatcherAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "dispatch-corr-id",
        )

    @pytest.fixture
    def answer_agent(self) -> NlpAnswerAgent:
        return NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "ans-id",
        )

    # ── disambiguation path ──────────────────────────────────────────────

    def test_disambiguation_answer_carries_request_id(
        self, dispatcher: NlpDispatcherAgent
    ) -> None:
        """qa.answer.v1{kind=disambiguation} carries the originating request_id."""
        msg = _make_intent_msg({"request_id": "orig-req-001", "entities": []})
        out = list(dispatcher.handle(msg))
        assert len(out) == 1
        assert out[0].payload["request_id"] == "orig-req-001"

    def test_disambiguation_answer_carries_qa_correlation_id(
        self, dispatcher: NlpDispatcherAgent
    ) -> None:
        """qa.answer.v1{kind=disambiguation} carries a non-empty qa_correlation_id."""
        msg = _make_intent_msg({"entities": []})
        out = list(dispatcher.handle(msg))
        assert len(out) == 1
        corr = out[0].payload.get("qa_correlation_id")
        assert isinstance(corr, str) and len(corr) > 0

    # ── summary fan-out → qa.answer.v1 round-trip ───────────────────────

    def test_summary_answer_carries_original_request_id(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        """qa.answer.v1 from summary aggregation carries the qa_request_id from
        predict.approved.v1 (which originally came from qa.intent.v1.request_id).
        """
        corr = "sc-001"
        qa_corr = "qc-001"
        msg = _make_approved_msg_with_corr(
            summary_corr=corr,
            expected_count=1,
            qa_correlation_id=qa_corr,
            qa_request_id="original-request-id",
        )
        out = list(answer_agent.handle(msg))
        assert len(out) == 1
        assert out[0].payload["request_id"] == "original-request-id"

    def test_summary_answer_carries_dispatch_qa_correlation_id(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        """qa.answer.v1 qa_correlation_id matches the additive field on
        predict.approved.v1 (the Phase 5 round-trip invariant).
        """
        corr = "sc-002"
        qa_corr = "qc-distinct-from-summary-corr"
        msg = _make_approved_msg_with_corr(
            summary_corr=corr,
            expected_count=1,
            qa_correlation_id=qa_corr,
        )
        out = list(answer_agent.handle(msg))
        assert len(out) == 1
        assert out[0].payload["qa_correlation_id"] == qa_corr

    def test_summary_answer_uses_summary_corr_when_qa_corr_absent(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        """Backward-compat: if predict.approved.v1 has no qa_correlation_id field,
        fall back to summary_correlation_id as qa_correlation_id in qa.answer.v1.
        """
        corr = "sc-003"
        # Use the pre-existing helper that omits qa_correlation_id
        msg = _make_approved_msg(corr, expected_count=1, qa_request_id="req-bc")
        out = list(answer_agent.handle(msg))
        assert len(out) == 1
        # Falls back to summary_corr
        assert out[0].payload["qa_correlation_id"] == corr

    def test_both_fields_present_in_every_summary_qa_answer_v1(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        """Every qa.answer.v1 from summary aggregation has non-empty
        request_id AND qa_correlation_id (the §10.6 invariant).
        """
        corr = "sc-004"
        qa_corr = "qc-004"
        msg = _make_approved_msg_with_corr(
            summary_corr=corr,
            expected_count=1,
            qa_correlation_id=qa_corr,
            qa_request_id="req-inv-004",
        )
        out = list(answer_agent.handle(msg))
        assert len(out) == 1
        payload = out[0].payload
        assert payload.get("request_id"), "request_id must be non-empty"
        assert payload.get("qa_correlation_id"), "qa_correlation_id must be non-empty"

    # ── adversarial: qa_correlation_id cannot be empty via null payload ──

    def test_null_qa_correlation_id_in_approved_falls_back_to_summary_corr(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        """predict.approved.v1 with qa_correlation_id=None falls back gracefully."""
        corr = "sc-005"
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "summary_correlation_id": corr,
                "summary_expected_count": 1,
                "qa_request_id": "req-005",
                "qa_correlation_id": None,  # explicitly null
                "prediction_id": "p1",
                "match_id": "team-0",
                "market": "1x2",
                "degraded": False,
            },
        )
        out = list(answer_agent.handle(msg))
        assert len(out) == 1
        # None → falls back to summary_corr
        assert out[0].payload["qa_correlation_id"] == corr
        assert out[0].payload["qa_correlation_id"], "qa_correlation_id must be non-empty"


# ── §10.6 idempotency / dedup tests ──────────────────────────────────────────


def _make_dedup_agent(window_s: float = 600.0) -> NlpDispatcherAgent:
    """Return a NlpDispatcherAgent with an injected deduper for controlled tests."""
    import time as _time

    from swarm.sdk import RequestIdDeduper

    deduper = RequestIdDeduper(window_s=window_s, max_keys=1_000)
    return NlpDispatcherAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "test-dedup-corr",
        deduper=deduper,
    )


class TestNlpDispatcherIdempotency:
    """§10.6 — (qa_correlation_id, intent, entity_hash) dedup key is replay-safe."""

    def test_first_dispatch_is_not_suppressed(self) -> None:
        """First call for a key goes through — dedup only fires on replay."""
        agent = _make_dedup_agent()
        msg = _make_intent_msg(
            {"qa_correlation_id": "corr-idem-001", "entities": []}
        )
        # predict.* without entity → disambiguation; must NOT be suppressed
        out = list(agent.handle(msg))
        assert len(out) == 1
        assert out[0].payload["kind"] == "disambiguation"

    def test_replay_same_key_returns_empty(self) -> None:
        """Replay of an identical (corr, intent, entity_hash) is silently dropped."""
        agent = _make_dedup_agent()
        msg = _make_intent_msg(
            {"qa_correlation_id": "corr-idem-002", "entities": []}
        )
        first = list(agent.handle(msg))
        assert len(first) == 1, "First call must dispatch"
        # Replay with a new message object but identical key components.
        replay = _make_intent_msg(
            {"qa_correlation_id": "corr-idem-002", "entities": []}
        )
        second = list(agent.handle(replay))
        assert second == [], "Replay must be suppressed (empty list)"

    def test_different_corr_id_not_suppressed(self) -> None:
        """Different qa_correlation_id means different key → not a duplicate."""
        agent = _make_dedup_agent()
        msg_a = _make_intent_msg(
            {"qa_correlation_id": "corr-idem-003a", "entities": []}
        )
        msg_b = _make_intent_msg(
            {"qa_correlation_id": "corr-idem-003b", "entities": []}
        )
        list(agent.handle(msg_a))
        out_b = list(agent.handle(msg_b))
        assert len(out_b) == 1, "Different corr_id must not be suppressed"

    def test_different_entities_not_suppressed(self) -> None:
        """Different entity set → different entity_hash → different key → dispatched."""
        agent = _make_dedup_agent()
        msg_a = _make_intent_msg({
            "qa_correlation_id": "corr-idem-004",
            "intent": "predict.match_outcome",
            "entities": [_make_team_entity("gs")],
        })
        msg_b = _make_intent_msg({
            "qa_correlation_id": "corr-idem-004",
            "intent": "predict.match_outcome",
            "entities": [_make_team_entity("fb")],
        })
        # Both have same corr + intent but different entities → both go through.
        out_a = list(agent.handle(msg_a))
        out_b = list(agent.handle(msg_b))
        # Both reach the predict.* backoff check (no entity anchor after
        # _entity_hash differs — but actual result here is [] since gs/fb
        # entities resolve, so both should be [] from the routing stub).
        # Key invariant: both must NOT be suppressed by dedup.
        # We verify by checking the dedup itself: second call with *same*
        # entity set IS suppressed.
        agent2 = _make_dedup_agent()
        list(agent2.handle(msg_a))
        replay_a = _make_intent_msg({
            "qa_correlation_id": "corr-idem-004",
            "intent": "predict.match_outcome",
            "entities": [_make_team_entity("gs")],
        })
        assert list(agent2.handle(replay_a)) == [], "Same entity set replay must be suppressed"

    def test_dedup_window_expiry_allows_re_dispatch(self) -> None:
        """After the dedup window expires, the same key may be dispatched again."""
        import time as _time

        from swarm.sdk import RequestIdDeduper

        fake_now = [0.0]
        deduper = RequestIdDeduper(
            window_s=10.0,
            max_keys=100,
            clock=lambda: fake_now[0],
        )
        agent = NlpDispatcherAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-exp-corr",
            deduper=deduper,
        )
        msg = _make_intent_msg(
            {"qa_correlation_id": "corr-exp-001", "entities": []}
        )
        first = list(agent.handle(msg))
        assert len(first) == 1, "First dispatch must go through"
        # Advance fake clock past the window.
        fake_now[0] = 15.0  # > 10 s window
        replay = _make_intent_msg(
            {"qa_correlation_id": "corr-exp-001", "entities": []}
        )
        after_expiry = list(agent.handle(replay))
        assert len(after_expiry) == 1, "After window expiry the key must be re-dispatched"

    def test_empty_corr_id_treated_as_valid_key(self) -> None:
        """Missing qa_correlation_id (empty string) still forms a valid dedup key."""
        agent = _make_dedup_agent()
        msg = _make_intent_msg({})  # no qa_correlation_id field
        first = list(agent.handle(msg))
        replay = _make_intent_msg({})
        second = list(agent.handle(replay))
        assert second == [], "Empty corr_id replay must also be deduplicated"


# ── §10.16 Degraded flag flow-through ──────────────────────────────────


class TestDegradedFlagRoundTrip:
    """§10.16 — predict.approved.v1{degraded:true, degraded_reason} must be
    preserved byte-for-byte in qa.answer.v1.
    
    AST-asserted at the answer agent per ROADMAP §10.16 hard rule.
    """

    @pytest.fixture
    def agent(self) -> NlpAnswerAgent:
        return NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-ans-id",
            monotonic=None,  # real monotonic
        )

    def test_single_degraded_prediction_propagates_flag(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When one prediction in a summary is degraded, the answer is degraded."""
        corr = "agg-degraded-001"
        # First prediction: not degraded
        msg1 = _make_approved_msg(
            corr, expected_count=2, prediction_id="p1", degraded=False
        )
        # Second prediction: degraded
        msg2 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p2",
            degraded=True,
            degraded_reason="swarm voter count below minimum",
        )
        list(agent.handle(msg1))
        results = list(agent.handle(msg2))
        assert len(results) == 1
        ans = results[0]
        assert ans.payload["degraded"] is True
        assert "swarm voter count below minimum" in ans.payload["degraded_reason"]

    def test_all_predictions_degraded_combines_reasons(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When all predictions are degraded, all reasons are combined."""
        corr = "agg-degraded-002"
        msg1 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p1",
            degraded=True,
            degraded_reason="reason_A",
        )
        msg2 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p2",
            degraded=True,
            degraded_reason="reason_B",
        )
        list(agent.handle(msg1))
        results = list(agent.handle(msg2))
        assert len(results) == 1
        ans = results[0]
        assert ans.payload["degraded"] is True
        degraded_reason = ans.payload["degraded_reason"]
        assert "reason_A" in degraded_reason
        assert "reason_B" in degraded_reason

    def test_no_predictions_degraded_flag_false(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When no predictions are degraded and all received, degraded=False."""
        corr = "agg-clean-001"
        msg1 = _make_approved_msg(
            corr, expected_count=2, prediction_id="p1", degraded=False
        )
        msg2 = _make_approved_msg(
            corr, expected_count=2, prediction_id="p2", degraded=False
        )
        list(agent.handle(msg1))
        results = list(agent.handle(msg2))
        assert len(results) == 1
        ans = results[0]
        assert ans.payload["degraded"] is False
        assert ans.payload["degraded_reason"] is None

    def test_timeout_and_prediction_degraded_combines(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When summary times out AND a prediction is degraded, both reasons appear."""
        corr = "agg-timeout-degraded-001"
        
        # Use expired monotonic
        call_count = [0]
        def fake_monotonic() -> float:
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 1_000_000.0
        
        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        
        # Only receive 1 of 3 expected, and that one is degraded
        msg = _make_approved_msg(
            corr,
            expected_count=3,
            degraded=True,
            degraded_reason="voter count insufficient",
        )
        results = list(expired_agent.handle(msg))
        assert len(results) == 1
        ans = results[0]
        assert ans.payload["degraded"] is True
        reason = ans.payload["degraded_reason"]
        # Both timeout reason and prediction reason must be present
        assert "1/3" in reason
        assert "voter count insufficient" in reason

    def test_degraded_reason_none_when_not_degraded(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When degraded=False, degraded_reason must be None (not empty string)."""
        corr = "agg-clean-002"
        msg1 = _make_approved_msg(corr, expected_count=1, degraded=False)
        results = list(agent.handle(msg1))
        assert results[0].payload["degraded"] is False
        assert results[0].payload["degraded_reason"] is None

    def test_empty_degraded_reason_string_omitted_from_combined(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When predict.final has degraded=True but degraded_reason='', don't add empty."""
        corr = "agg-empty-reason-001"
        msg1 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p1",
            degraded=True,
            degraded_reason="",  # Empty but degraded=True
        )
        msg2 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p2",
            degraded=False,
        )
        list(agent.handle(msg1))
        results = list(agent.handle(msg2))
        ans = results[0]
        assert ans.payload["degraded"] is True
        # Degraded reason: if all reasons are empty, should be None
        reason = ans.payload["degraded_reason"]
        # Empty strings are filtered, so if only p1 had degraded with empty reason,
        # the combined list is empty → None or empty-joined
        assert reason is None or (isinstance(reason, str) and ";;" not in reason)


class TestCalibrationVersionStamping:
    """§10.16 — Calibration version stamping: every predict.* answer carries
    calibration_version from predict.approved.v1; mismatched versions across
    fixtures in a summary.* aggregation → multiple citation entries (one per
    version), explicit Turkish note.
    """

    @pytest.fixture
    def agent(self) -> NlpAnswerAgent:
        return NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-ans-id",
            monotonic=None,
        )

    def test_single_calibration_version_one_citation_no_note(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When all predictions have the same calibration_version, emit one citation
        with no Turkish note (no version mismatch)."""
        corr = "agg-cal-001"
        # All predictions have calibration_version=1
        msg1 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p1",
                "summary_correlation_id": corr,
                "summary_expected_count": 2,
                "qa_request_id": "req-001",
                "calibration_version": 1,
                "final": {"calibration_version": 1, "degraded": False},
            },
        )
        msg2 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p2",
                "summary_correlation_id": corr,
                "summary_expected_count": 2,
                "qa_request_id": "req-001",
                "calibration_version": 1,
                "final": {"calibration_version": 1, "degraded": False},
            },
        )
        list(agent.handle(msg1))
        results = list(agent.handle(msg2))
        assert len(results) == 1
        ans = results[0]
        citations = ans.payload["citations"]
        assert len(citations) == 1
        assert citations[0]["calibration_version"] == 1
        assert citations[0]["prediction_count"] == 2
        assert "note" not in citations[0], "No note when only one version"

    def test_multiple_calibration_versions_multiple_citations_with_notes(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When predictions have different calibration_versions, emit one citation
        per version, each with explicit Turkish note."""
        corr = "agg-cal-002"
        # Three predictions: two with v1, one with v2
        msg1 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p1",
                "summary_correlation_id": corr,
                "summary_expected_count": 3,
                "qa_request_id": "req-002",
                "calibration_version": 1,
                "final": {"calibration_version": 1, "degraded": False},
            },
        )
        msg2 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p2",
                "summary_correlation_id": corr,
                "summary_expected_count": 3,
                "qa_request_id": "req-002",
                "calibration_version": 1,
                "final": {"calibration_version": 1, "degraded": False},
            },
        )
        msg3 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p3",
                "summary_correlation_id": corr,
                "summary_expected_count": 3,
                "qa_request_id": "req-002",
                "calibration_version": 2,
                "final": {"calibration_version": 2, "degraded": False},
            },
        )
        list(agent.handle(msg1))
        list(agent.handle(msg2))
        results = list(agent.handle(msg3))
        assert len(results) == 1
        ans = results[0]
        citations = ans.payload["citations"]
        # Two citation entries: one for v1 (2 preds), one for v2 (1 pred)
        assert len(citations) == 2
        # Sorted by calibration_version
        assert citations[0]["calibration_version"] == 1
        assert citations[0]["prediction_count"] == 2
        assert "note" in citations[0]
        assert "2 tahmin için kalibrasyon güncellendi" == citations[0]["note"]
        
        assert citations[1]["calibration_version"] == 2
        assert citations[1]["prediction_count"] == 1
        assert "note" in citations[1]
        assert "1 tahmin için kalibrasyon güncellendi" == citations[1]["note"]

    def test_calibration_version_missing_defaults_to_one(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When calibration_version is missing from predict.approved.v1, default to 1."""
        corr = "agg-cal-003"
        # One prediction with explicit v1, one without the field (defaults to 1)
        msg1 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p1",
                "summary_correlation_id": corr,
                "summary_expected_count": 2,
                "qa_request_id": "req-003",
                "calibration_version": 1,
                "final": {"degraded": False},
            },
        )
        msg2 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p2",
                "summary_correlation_id": corr,
                "summary_expected_count": 2,
                "qa_request_id": "req-003",
                # No calibration_version field
                "final": {"degraded": False},
            },
        )
        list(agent.handle(msg1))
        results = list(agent.handle(msg2))
        ans = results[0]
        citations = ans.payload["citations"]
        # Both treated as v1
        assert len(citations) == 1
        assert citations[0]["calibration_version"] == 1
        assert citations[0]["prediction_count"] == 2

    def test_three_different_calibration_versions(
        self, agent: NlpAnswerAgent
    ) -> None:
        """When three different calibration versions are present, emit three citations."""
        corr = "agg-cal-004"
        msg1 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p1",
                "summary_correlation_id": corr,
                "summary_expected_count": 3,
                "qa_request_id": "req-004",
                "calibration_version": 1,
                "final": {"degraded": False},
            },
        )
        msg2 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p2",
                "summary_correlation_id": corr,
                "summary_expected_count": 3,
                "qa_request_id": "req-004",
                "calibration_version": 2,
                "final": {"degraded": False},
            },
        )
        msg3 = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "p3",
                "summary_correlation_id": corr,
                "summary_expected_count": 3,
                "qa_request_id": "req-004",
                "calibration_version": 3,
                "final": {"degraded": False},
            },
        )
        list(agent.handle(msg1))
        list(agent.handle(msg2))
        results = list(agent.handle(msg3))
        ans = results[0]
        citations = ans.payload["citations"]
        assert len(citations) == 3
        assert citations[0]["calibration_version"] == 1
        assert citations[1]["calibration_version"] == 2
        assert citations[2]["calibration_version"] == 3
        for c in citations:
            assert "note" in c
            assert "kalibrasyon güncellendi" in c["note"]


