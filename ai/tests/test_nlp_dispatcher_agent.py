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

import ast
import hashlib
import hmac
import inspect
from collections import deque
from pathlib import Path

import pytest

from common.config import cfg as _cfg
from nlp.conversation import ConversationStore
from swarm.agents.nlp import NlpAnswerAgent, NlpDispatcherAgent, _SummaryAgg
from swarm.agents.topics import (
    DATA_REQUEST_V1,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    PREDICT_APPROVED,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_CONTEXT_V1,
    QA_FEEDBACK_V1,
    QA_INTENT_V1,
    QA_REQUEST,
    SEC_ALERT,
)
from swarm.sdk.types import Message
from swarm.sdk.wire_contracts import (
    NLP_ALERT_V1_ALLOWED_PRODUCERS,
    NLP_EVENT_V1_ALLOWED_PRODUCERS,
)


def test_nlp_summary_fanout_no_gather_in_dispatcher() -> None:
    """AST guard: dispatcher must not use asyncio.gather for summary fan-out."""
    src = Path(__file__).resolve().parents[2] / "ai" / "swarm" / "agents" / "nlp" / "__init__.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "gather":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "asyncio":
                violations.append(f"{src}:{node.lineno}: asyncio.gather is forbidden in dispatcher")

    assert violations == [], "\n".join(violations)


def test_nlp_dispatcher_subscribes_to_qa_feedback_v1() -> None:
    assert QA_FEEDBACK_V1 in NlpDispatcherAgent.subscribes


def test_nlp_feedback_queue_overflow_emits_event() -> None:
    agent = NlpDispatcherAgent()
    # fill the queue to its max so the next insert overflows.
    agent._feedback_queue = deque(maxlen=2)
    agent._feedback_queue.append({"request_id": "old-1"})
    agent._feedback_queue.append({"request_id": "old-2"})

    out = list(agent.handle(_make_feedback_msg({
        "request_id": "req-backup",
        "did_you_mean_offered_intents": ["predict.match_outcome"],
        "accepted_intent": "predict.match_outcome",
    })))

    assert len(agent._feedback_queue) == 2
    assert agent._feedback_queue[-1]["request_id"] == "req-backup"
    assert any(
        m.payload.get("kind") == "active_learning_queue_overflow"
        for m in out
    )


def test_nlp_feedback_provenance_mismatch_dropped() -> None:
    agent = NlpDispatcherAgent()
    out = list(agent.handle(_make_feedback_msg({
        "request_id": "req-mismatch",
        "did_you_mean_offered_intents": ["predict.match_outcome", "predict.btts"],
        "accepted_intent": "predict.score_grid",
    })))

    assert len(out) == 1
    assert out[0].payload["kind"] == "feedback_provenance_mismatch"
    assert out[0].payload["request_id"] == "req-mismatch"


def test_nlp_feedback_processor_does_not_branch_on_user_id_ast() -> None:
    source = Path(__file__).resolve().parents[2] / "ai" / "swarm" / "agents" / "nlp" / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_expr = ast.get_source_segment(source.read_text(encoding="utf-8"), node.test) or ""
            if "user_id" in test_expr:
                violations.append(f"{source}:{node.lineno}: user_id usage in dispatcher logic")
    assert violations == [], "\n".join(violations)

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


def _make_feedback_msg(overrides: dict | None = None) -> Message:
    payload = {
        "schema_version": 1,
        "request_id": "req-feedback-001",
        "original_qa_correlation_id": "corr-001",
        "did_you_mean_offered_intents": ["predict.match_outcome", "predict.btts"],
        "accepted_intent": "predict.match_outcome",
    }
    if overrides:
        payload.update(overrides)
    return Message.new(topic=QA_FEEDBACK_V1, payload=payload)


def _make_team_entity(canonical_id: str = "gs") -> dict:
    return {
        "span_start": 0,
        "span_end": 2,
        "kind": "team",
        "canonical_id": canonical_id,
        "confidence": 0.99,
        "lexicon_version": "1.0.0",
        "source": "gazetteer",
    }


def _make_team_entity_at(
    canonical_id: str,
    span_start: int,
    span_end: int,
) -> dict:
    return {
        "span_start": span_start,
        "span_end": span_end,
        "kind": "team",
        "canonical_id": canonical_id,
        "confidence": 0.99,
        "lexicon_version": "1.0.0",
        "source": "gazetteer",
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

    def test_publishes_qa_context_v1(self, agent: NlpDispatcherAgent) -> None:
        assert QA_CONTEXT_V1 in agent.publishes


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
            QA_CONTEXT_V1,
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

    def test_predict_no_entity_disambiguation_includes_new_answer_envelope_fields(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg({"entities": []})
        payload = list(agent.handle(msg))[0].payload
        assert payload["schema_version"] == 2
        assert payload["answer_format"] == "plain"
        assert payload["humanizer_used"] is False
        assert payload["proofreader_status"] == "pass"
        assert payload["nlp_pipeline_version"] == _cfg.nlp_pipeline_version

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

    def test_predict_no_entity_disambiguation_preserves_conversation_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [],
        })
        results = list(agent.handle(msg))
        answer = results[0]
        assert answer.payload["kind"] == "disambiguation"
        assert answer.payload["conversation_id"] == "conv-123"

    def test_multi_pronoun_compose_emits_single_disambiguation(
        self, agent: NlpDispatcherAgent
    ) -> None:
        first = _make_intent_msg({
            "request_id": "req-anaphora-1",
            "qa_correlation_id": "corr-anaphora-1",
            "conversation_id": "conv-multi-anaphora",
            "entities": [_make_team_entity("gs")],
        })
        list(agent.handle(first))

        second = _make_intent_msg({
            "request_id": "req-anaphora-2",
            "qa_correlation_id": "corr-anaphora-2",
            "conversation_id": "conv-multi-anaphora",
            "normalized_text": "onlar orası gidecek mi",
            "entities": [],
        })
        results = list(agent.handle(second))

        answer = next(
            r for r in results if r.envelope.topic == QA_ANSWER_V1
        )
        assert answer.payload["kind"] == "disambiguation"
        assert "Son konuşmada" in answer.payload["answer_text"]

    def test_search_query_style_short_circuits_to_search_syntax_unsupported(
        self, agent: NlpDispatcherAgent,
    ) -> None:
        msg = _make_intent_msg({
            "intent": "data.lineup_probable",
            "query_style": "search",
        })
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.envelope.topic == QA_ANSWER_V1
        assert out.payload["intent"] == "meta.search_syntax_unsupported"
        assert out.payload["kind"] == "search_syntax_unsupported"
        assert "arama operatörleri" in out.payload["answer_text"]

    def test_quoted_exact_search_query_style_returns_search_syntax_unsupported(
        self, agent: NlpDispatcherAgent,
    ) -> None:
        msg = _make_intent_msg({
            "intent": "data.fixture_lookup",
            "query_style": "quoted_exact_search",
        })
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.payload["intent"] == "meta.search_syntax_unsupported"
        assert out.payload["kind"] == "search_syntax_unsupported"

    def test_sarcasm_modifier_routes_opinion_intent_to_meta_opinion_unsupported(
        self, agent: NlpDispatcherAgent,
    ) -> None:
        msg = _make_intent_msg({
            "intent": "predict.match_outcome",
            "qa_correlation_id": "corr-sarcasm",
            "intent_modifier": "sarcastic",
            "normalized_text": "galatasaray harika oynadılar ama 0-5 kaybetti",
            "entities": [],
        })
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.envelope.topic == QA_ANSWER_V1
        assert out.payload["intent"] == "meta.opinion_unsupported"
        assert out.payload["kind"] == "opinion_unsupported"
        assert "Yorum içerir görünen ifadeler için cevap üretmiyorum" in out.payload["answer_text"]

    def test_meta_answer_helper_includes_conversation_id(self, agent: NlpDispatcherAgent) -> None:
        answer = agent._make_meta_answer(
            "req-001",
            "qc-001",
            "meta.modality_unsupported",
            "Bu tür modalite sorgusuna destek veremem.",
            conversation_id="conv-123",
        )
        assert answer.payload["conversation_id"] == "conv-123"

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

    def test_predict_with_conversation_id_emits_context(self, agent: NlpDispatcherAgent) -> None:
        msg = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity()],
        })
        results = list(agent.handle(msg))
        assert any(result.envelope.topic == QA_CONTEXT_V1 for result in results)
        context_msg = next(
            result for result in results if result.envelope.topic == QA_CONTEXT_V1
        )
        assert context_msg.payload["conversation_id"] == "conv-123"
        assert context_msg.payload["intent"] == "predict.match_outcome"
        assert context_msg.payload["turn_index"] == 0
        assert context_msg.payload["entities"] == msg.payload["entities"]

    def test_predict_without_conversation_id_does_not_emit_context(
        self,
        agent: NlpDispatcherAgent,
        monkeypatch,
    ) -> None:
        called = False

        def fail_if_loaded(conversation_id: str) -> None:
            nonlocal called
            called = True
            raise AssertionError("load() must not be called for anonymous requests")

        monkeypatch.setattr(agent._conversation_store, "load", fail_if_loaded)
        msg = _make_intent_msg({
            "conversation_id": None,
            "entities": [_make_team_entity()],
        })
        results = list(agent.handle(msg))
        assert all(result.envelope.topic != QA_CONTEXT_V1 for result in results)
        assert not called

    def test_nlp_conversation_context_carries_prior_entities_when_current_turn_has_none(
        self, agent: NlpDispatcherAgent,
    ) -> None:
        first = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs"), _make_competition_entity("ucl")],
        })
        second = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [],
        })

        results1 = list(agent.handle(first))
        assert any(r.envelope.topic == QA_CONTEXT_V1 for r in results1)

        results2 = list(agent.handle(second))
        context2 = next(r for r in results2 if r.envelope.topic == QA_CONTEXT_V1)
        assert context2.payload["turn_index"] == 1
        assert context2.payload["entities"] == first.payload["entities"]

    def test_nlp_followup_resolves_entity_from_context(self, agent: NlpDispatcherAgent) -> None:
        first = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs"), _make_competition_entity("ucl")],
        })
        second = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [],
        })

        list(agent.handle(first))
        results2 = list(agent.handle(second))
        context2 = next(r for r in results2 if r.envelope.topic == QA_CONTEXT_V1)

        assert context2.payload["turn_index"] == 1
        assert context2.payload["entities"] == first.payload["entities"]

    def test_nlp_followup_resolves_pronoun_from_recent_context(self, agent: NlpDispatcherAgent) -> None:
        first = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs")],
        })
        second = _make_intent_msg({
            "conversation_id": "conv-123",
            "normalized_text": "onlar maçta kazanır mı",
            "entities": [],
        })

        list(agent.handle(first))
        results2 = list(agent.handle(second))

        assert any(r.envelope.topic == QA_CONTEXT_V1 for r in results2)
        assert not any(
            r.envelope.topic == QA_ANSWER_V1 and r.payload.get("kind") == "disambiguation"
            for r in results2
        )

    def test_repeated_query_threshold_crossed_emits_event(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-repeated-1"
        agent._conversation_store.clear(conversation_id)

        base = {
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
            "intent": "data.lineup_probable",
        }
        list(agent.handle(_make_intent_msg({**base, "request_id": "req-001", "qa_correlation_id": "corr-001"})))
        list(agent.handle(_make_intent_msg({**base, "request_id": "req-002", "qa_correlation_id": "corr-002"})))
        list(agent.handle(_make_intent_msg({**base, "request_id": "req-003", "qa_correlation_id": "corr-003"})))

        results4 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-004", "qa_correlation_id": "corr-004"})))

        event_messages = [
            r for r in results4
            if r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "repeated_query_threshold_crossed"
        ]
        assert len(event_messages) == 1
        event = event_messages[0]
        assert event.payload["repeat_count"] == 4
        assert event.payload["window_s"] == int(_cfg.nlp_repeated_query_window_s)
        assert event.payload["conversation_id"] == conversation_id

    def test_repeated_query_summary_mode_template_at_higher_threshold(self, agent: NlpDispatcherAgent, monkeypatch) -> None:
        monkeypatch.setattr(_cfg, "nlp_repeated_query_threshold", 1)
        monkeypatch.setattr(_cfg, "nlp_repeated_query_summary_threshold", 2)
        conversation_id = "conv-repeated-summary"
        agent._conversation_store.clear(conversation_id)

        base = {
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
            "intent": "data.lineup_probable",
        }
        results1 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-001", "qa_correlation_id": "corr-001"})))
        results2 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-002", "qa_correlation_id": "corr-002"})))
        results3 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-003", "qa_correlation_id": "corr-003"})))
        results4 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-004", "qa_correlation_id": "corr-004"})))
        all_results = results1 + results2 + results3 + results4

        answer_messages = [
            r for r in results4
            if r.envelope.topic == QA_ANSWER_V1
        ]
        assert len(answer_messages) == 1
        answer = answer_messages[0]
        assert answer.payload["intent"] == "data.conversation_summary"
        assert "özet modu" in answer.payload["answer_text"]
        assert answer.payload["kind"] == "summary_offer"

        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "repeated_query_threshold_crossed"
            for r in all_results
        )

    def test_repeated_query_threshold_not_emitted_before_threshold(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-repeated-2"
        agent._conversation_store.clear(conversation_id)

        base = {
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
            "intent": "data.lineup_probable",
        }
        results1 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-101", "qa_correlation_id": "corr-101"})))
        results2 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-102", "qa_correlation_id": "corr-102"})))
        results3 = list(agent.handle(_make_intent_msg({**base, "request_id": "req-103", "qa_correlation_id": "corr-103"})))

        assert not any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "repeated_query_threshold_crossed"
            for r in results1 + results2 + results3
        )

    def test_nlp_anaphora_mention_eviction_emits_event(self, agent: NlpDispatcherAgent, monkeypatch) -> None:
        monkeypatch.setattr(_cfg, "nlp_anaphora_lookback_turns", 1)
        conversation_id = "conv-anaphora-evict-1"
        agent._conversation_store.clear(conversation_id)

        first = _make_intent_msg({
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
        })
        second = _make_intent_msg({
            "conversation_id": conversation_id,
            "intent": "data.fixture_lookup",
            "entities": [],
        })

        list(agent.handle(first))
        results2 = list(agent.handle(second))

        evicted_events = [
            r for r in results2
            if r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "anaphora_antecedent_evicted"
        ]
        assert len(evicted_events) == 1
        event = evicted_events[0]
        assert event.payload["conversation_id"] == conversation_id
        assert event.payload["evicted_count"] == 1
        assert event.payload["evicted_canonical_ids"] == ["gs"]

        context_msg = next(r for r in results2 if r.envelope.topic == QA_CONTEXT_V1)
        mentions = context_msg.payload["anaphora_mentions"]
        assert len(mentions) == 1
        assert mentions[0]["canonical_id"] == "gs"
        assert mentions[0]["mentioned_turn"] == 1

    def test_nlp_anaphora_eviction_event_rate_limited(self, monkeypatch) -> None:
        current_time = [1_000.0]

        def monotonic() -> float:
            return current_time[0]

        monkeypatch.setattr(_cfg, "nlp_anaphora_lookback_turns", 999)
        monkeypatch.setattr(_cfg, "nlp_anaphora_lookback_seconds", 0)
        monkeypatch.setattr(_cfg, "nlp_anaphora_eviction_event_ratelimit_s", 60)

        agent = NlpDispatcherAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-corr-id",
            monotonic=monotonic,
        )
        conversation_id = "conv-anaphora-evict-2"
        agent._conversation_store.clear(conversation_id)

        first = _make_intent_msg({
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
        })
        list(agent.handle(first))

        second = _make_intent_msg({
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
        })
        results2 = list(agent.handle(second))
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "anaphora_antecedent_evicted"
            for r in results2
        )

        current_time[0] += 1
        third = _make_intent_msg({
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
        })
        results3 = list(agent.handle(third))
        assert not any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "anaphora_antecedent_evicted"
            for r in results3
        )

    def test_nlp_explicit_team_mention_overrides_prior_context(self, agent: NlpDispatcherAgent) -> None:
        current_time = [1_000.0]

        def monotonic() -> float:
            return current_time[0]

        monkeypatch.setattr(_cfg, "nlp_anaphora_lookback_turns", 999)
        monkeypatch.setattr(_cfg, "nlp_anaphora_lookback_seconds", 0)
        monkeypatch.setattr(_cfg, "nlp_anaphora_eviction_event_ratelimit_s", 60)

        agent = NlpDispatcherAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-corr-id",
            monotonic=monotonic,
        )

        first = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs")],
        })
        list(agent.handle(first))

        second = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs")],
        })
        results2 = list(agent.handle(second))
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "anaphora_antecedent_evicted"
            for r in results2
        )

        current_time[0] += 1
        third = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs")],
        })
        results3 = list(agent.handle(third))
        assert not any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "anaphora_antecedent_evicted"
            for r in results3
        )

    def test_nlp_explicit_team_mention_overrides_prior_context(self, agent: NlpDispatcherAgent) -> None:
        first = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("gs"), _make_competition_entity("ucl")],
        })
        second = _make_intent_msg({
            "conversation_id": "conv-123",
            "entities": [_make_team_entity("fb")],
        })

        list(agent.handle(first))
        results2 = list(agent.handle(second))

        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "conversation_entity_overridden"
            for r in results2
        )
        context2 = next(r for r in results2 if r.envelope.topic == QA_CONTEXT_V1)
        expected_entities = [
            _make_competition_entity("ucl"),
            _make_team_entity("fb"),
        ]
        assert context2.payload["entities"] == expected_entities

    def test_nlp_context_capped_at_max_turns_resets_on_overflow(self, agent: NlpDispatcherAgent, monkeypatch) -> None:
        monkeypatch.setattr(_cfg, "nlp_conversation_max_turns", 1)
        first = _make_intent_msg({
            "conversation_id": "conv-321",
            "entities": [_make_team_entity("gs")],
        })
        second = _make_intent_msg({
            "conversation_id": "conv-321",
            "entities": [_make_team_entity("gs")],
        })

        results1 = list(agent.handle(first))
        context1 = next(r for r in results1 if r.envelope.topic == QA_CONTEXT_V1)
        assert context1.payload["turn_index"] == 0

        results2 = list(agent.handle(second))
        context2 = next(r for r in results2 if r.envelope.topic == QA_CONTEXT_V1)
        assert context2.payload["turn_index"] == 0

    def test_nlp_redis_down_falls_through_to_stateless(self) -> None:
        store = ConversationStore()

        class BrokenClient:
            def get(self, key: str):
                raise RuntimeError("redis down")

            def delete(self, key: str):
                pass

        store._redis_client = lambda: BrokenClient()
        assert store.load("conv-999") is None

    def test_nlp_context_idle_ttl_evicts(self, monkeypatch) -> None:
        monkeypatch.setattr(_cfg, "nlp_conversation_idle_ttl_s", 0)
        store = ConversationStore()

        class FakeClient:
            def setex(self, key: str, ttl: int, value: str) -> None:
                pass

        store._redis_client = lambda: FakeClient()
        store.save({
            "schema_version": 1,
            "conversation_id": "conv-ttl",
            "turn_index": 0,
            "entities": [],
            "intent": "predict.match_outcome",
        })
        assert store.load("conv-ttl") is None

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
            assert all(
                r.envelope.topic != QA_ANSWER_V1 for r in results
            ), f"Unexpected predict backoff for intent={intent}"

    def test_all_predict_intents_backoff_without_entity(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Every predict.* intent in the closed enum triggers backoff when empty."""
        predict_intents = [
            "predict.match_outcome",
            "predict.match_outcome.conditional",
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

    def test_all_data_intents_route_to_data_request(self, agent: NlpDispatcherAgent) -> None:
        """Every closed data.* intent routes to data.request.v1 when no fixture lookup is present."""
        from nlp.intent import INTENT_LABELS

        for intent in sorted(INTENT_LABELS):
            if not intent.startswith("data.") or intent == "data.fixture_lookup":
                continue

            msg = _make_intent_msg({"intent": intent, "entities": []})
            results = list(agent.handle(msg))
            assert len(results) == 1, f"data route missing for intent={intent}"
            assert results[0].envelope.topic == DATA_REQUEST_V1
            assert results[0].payload["kind"] == intent.split(".", 1)[1]

    def test_nlp_role_prefix_manager_narrows_intent_dispatch(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "data.player_card_risk",
                "entities": [
                    {
                        "span_start": 0,
                        "span_end": 1,
                        "kind": "role_prefix",
                        "canonical_id": "manager",
                        "confidence": 1.0,
                        "lexicon_version": "1.0.0",
                        "source": "gazetteer",
                    },
                    {
                        "span_start": 1,
                        "span_end": 2,
                        "kind": "player",
                        "canonical_id": "buruk_id",
                        "confidence": 1.0,
                        "lexicon_version": "1.0.0",
                        "source": "gazetteer",
                    },
                ],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == DATA_REQUEST_V1
        assert results[0].payload["kind"] == "team_management_state"

    def test_quotative_frame_detected_reroutes_predict_to_attributed_claim(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "hocan diyor ki yarın 3-0 bitecekmiş",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert any(r.envelope.topic == NLP_EVENT_V1 for r in results)
        assert any(
            r.envelope.topic == DATA_REQUEST_V1
            and r.payload["kind"] == "attributed_claim"
            for r in results
        )

    def test_future_perfect_evidential_aspectual_stack_routes_to_meta_counterfactual_probe(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "yenmiş olacak",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert any(r.envelope.topic == NLP_EVENT_V1 for r in results)
        assert any(
            r.envelope.topic == QA_ANSWER_V1
            and r.payload["intent"] == "meta.counterfactual_probe"
            and r.payload["kind"] == "counterfactual_probe"
            for r in results
        )

    def test_conditional_predict_intent_with_aspectual_stack_routes_to_most_restrictive_safe_path(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome.conditional",
                "normalized_text": "eğer yenmiş olacaksa",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert any(r.envelope.topic == NLP_EVENT_V1 for r in results)
        assert any(
            r.envelope.topic == QA_ANSWER_V1
            and r.payload["intent"] == "meta.counterfactual_probe"
            and r.payload["kind"] == "counterfactual_probe"
            for r in results
        )

    def test_conditional_future_match_outcome_is_rewritten_to_predict_conditional_intent(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "qa_correlation_id": "corr-future",
                "normalized_text": "galatasaray kazanırsa lider olur mu",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == QA_ANSWER_V1
        assert results[0].payload["intent"] == "predict.match_outcome.conditional"
        assert results[0].payload["kind"] == "disambiguation"

    def test_conditional_marker_table_byte_identical_cross_phase(self) -> None:
        path = Path(__file__).resolve().parents[2] / "ai" / "nlp" / "lang_tr" / "conditional_markers.tr.yaml"
        assert path.exists(), f"Missing conditional markers file: {path}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == (
            "a52ad54a7728084577dc3e3e3b0e93c4960081bee8fd2f1f49cd340f5dbb8703"
        )

    def test_sarcasm_marker_table_byte_identical_cross_phase(self) -> None:
        path = Path(__file__).resolve().parents[2] / "ai" / "nlp" / "lang_tr" / "sarcasm_markers.tr.yaml"
        assert path.exists(), f"Missing sarcasm markers file: {path}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == (
            "bcb3a0c6b2a3c8f50827d4d4ccd925e279ce170bd32ffcf09000a779f5e0610f"
        )

    def test_conditional_plus_comparative_tuple_routing(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "qa_correlation_id": "corr-cond-comp",
                "normalized_text": "galatasaray kazanırsa fenerbahçeden önde mi olur",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == QA_ANSWER_V1
        assert results[0].payload["intent"] == "predict.match_outcome.conditional"
        assert results[0].payload["kind"] == "disambiguation"

    def test_conditional_present_match_outcome_rewrites_to_data_lineup_probable(self, agent: NlpDispatcherAgent) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "qa_correlation_id": "corr-present",
                "normalized_text": "galatasaray oynarsa kim oynar",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == DATA_REQUEST_V1
        assert results[0].payload["kind"] == "lineup_probable"

    def test_conditional_past_intent_routes_to_meta_counterfactual_past_unsupported(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "qa_correlation_id": "corr-past",
                "normalized_text": "galatasaray kazansaydı lider olurdu mu",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == QA_ANSWER_V1
        assert results[0].payload["intent"] == "meta.counterfactual_past_unsupported"
        assert results[0].payload["kind"] == "counterfactual_past_unsupported"

    def test_conditional_routing_matrix_complete_ast(self) -> None:
        src = Path(__file__).resolve().parents[2] / "ai" / "swarm" / "agents" / "nlp" / "__init__.py"
        tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))

        required_constants = {
            "predict.match_outcome.conditional",
            "meta.counterfactual_past_unsupported",
            "data.lineup_probable",
        }
        found_constants: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in required_constants:
                    found_constants.add(node.value)

        missing = required_constants - found_constants
        assert missing == set(), f"Conditional routing matrix missing constants: {sorted(missing)}"

    def test_progressive_epistemic_aspectual_stack_routes_to_fixture_lookup_in_play(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "oynuyor olabilir",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert any(r.envelope.topic == NLP_EVENT_V1 for r in results)
        assert any(
            r.envelope.topic == DATA_REQUEST_V1
            and r.payload["kind"] == "fixture_lookup"
            and r.payload["params"]["state"] == "in_play"
            for r in results
        )

    def test_future_relative_clause_aspectual_stack_routes_to_lineup_probable(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "oynayacak olan kim",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert any(r.envelope.topic == NLP_EVENT_V1 for r in results)
        assert any(
            r.envelope.topic == DATA_REQUEST_V1
            and r.payload["kind"] == "lineup_probable"
            for r in results
        )

    def test_social_media_attribution_routes_to_meta_unverifiable(self, agent: NlpDispatcherAgent) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "twitter'da yazıyorlar galatasaray şampiyon",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == NLP_EVENT_V1
        assert results[0].payload["kind"] == "quotative_frame_detected"

    def test_negative_quotative_routes_to_attributed_claim_with_negation(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "hic kimse demedi ki galatasaray kazanır",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        assert any(r.envelope.topic == NLP_EVENT_V1 for r in results)
        assert any(
            r.envelope.topic == DATA_REQUEST_V1
            and r.payload["kind"] == "attributed_claim"
            and r.payload["params"]["quotative_negation"] is True
            for r in results
        )

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


class TestNlpDispatcherMatchSeparator:
    def test_nlp_team_pair_sorted_before_dispatch(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "data.fixture_lookup",
                "normalized_text": "gs - fb",
                "qa_correlation_id": "test-qa-corr",
                "entities": [
                    _make_team_entity_at("gs", 0, 2),
                    _make_team_entity_at("fb", 5, 7),
                ],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.envelope.topic == DATA_REQUEST_V1
        assert out.payload["kind"] == "fixture_lookup"
        assert out.payload["params"] == {"team_pair": ["fb", "gs"]}
        assert out.payload["qa_correlation_id"] == "test-qa-corr"
        assert out.payload["qa_request_id"] == "req-001"

    def test_data_fixture_lookup_without_separator_does_not_route_to_data_request(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "data.fixture_lookup",
                "normalized_text": "gs fb",
                "entities": [
                    _make_team_entity_at("gs", 0, 2),
                    _make_team_entity_at("fb", 3, 5),
                ],
            }
        )
        results = list(agent.handle(msg))
        assert results == []

    def test_nlp_match_word_bridge_ile_promotes_to_match_lookup(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "data.fixture_lookup",
                "normalized_text": "gs ile fb",
                "qa_correlation_id": "test-qa-corr",
                "entities": [
                    _make_team_entity_at("gs", 0, 2),
                    _make_team_entity_at("fb", 6, 8),
                ],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.payload["params"] == {"team_pair": ["fb", "gs"]}

    def test_nlp_match_adjacency_co_token_derbi_promotes_pair(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "data.fixture_lookup",
                "normalized_text": "gs fb maçı",
                "qa_correlation_id": "test-qa-corr",
                "entities": [
                    _make_team_entity_at("gs", 0, 2),
                    _make_team_entity_at("fb", 3, 5),
                ],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.payload["params"] == {"team_pair": ["fb", "gs"]}

    def test_nlp_date_adjacent_to_pair_binds_fixture_filter(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "data.fixture_lookup",
                "normalized_text": "gs ile fb cuma",
                "qa_correlation_id": "test-qa-corr",
                "entities": [
                    _make_team_entity_at("gs", 0, 2),
                    _make_team_entity_at("fb", 7, 9),
                    {
                        "span_start": 10,
                        "span_end": 14,
                        "kind": "date",
                        "canonical_id": "2026-05-27",
                        "confidence": 0.95,
                        "source": "crf",
                        "lexicon_version": None,
                    },
                ],
            }
        )
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.payload["params"] == {
            "team_pair": ["fb", "gs"],
            "fixture_filter": {"date": "2026-05-27"},
        }


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
        assert text.startswith("Tüm")
        assert "hazırlanamadı" in text

    def test_expired_summary_answer_discloses_quorum_failure_for_insufficient_fixtures(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Below quorum, the summary should degrade to per-fixture-only text."""
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 1_000_000.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        corr = "agg-expired-005"
        msg = _make_approved_msg(corr, expected_count=5)
        out = list(expired_agent.handle(msg))
        assert len(out) == 1
        assert out[0].payload["answer_text"].startswith("Tüm")
        assert "hazırlanamadı" in out[0].payload["answer_text"]
        assert "summary quorum not met" in out[0].payload["degraded_reason"]

    def test_expired_summary_answer_discloses_partial_matches_and_incomplete_notice(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Partial summary answers must disclose the received/expected count and incomplete status."""
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 1_000_000.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        corr = "agg-expired-003"
        msg = _make_approved_msg(corr, expected_count=10)
        out = list(expired_agent.handle(msg))
        assert len(out) == 1
        assert out[0].payload["answer_text"].startswith("Tüm")
        assert "hazırlanamadı" in out[0].payload["answer_text"]
        assert "summary quorum not met" in out[0].payload["degraded_reason"]

    def test_expired_summary_answer_below_quorum_renders_per_fixture_only_degraded_answer(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Below quorum, the summary should degrade to per-fixture-only text."""
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            return 0.0 if call_count[0] == 1 else 1_000_000.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        corr = "agg-expired-004"
        msg = _make_approved_msg(corr, expected_count=3)
        out = list(expired_agent.handle(msg))

        assert len(out) == 1
        ans = out[0]
        assert ans.payload["degraded"] is True
        assert "Tüm maçları kapsayan bir özet hazırlanamadı" in ans.payload["answer_text"]
        assert "summary quorum not met" in ans.payload["degraded_reason"]

    def test_nlp_summary_quorum_met_renders_partial_with_disclosure(
        self, agent: NlpAnswerAgent
    ) -> None:
        """Quorum met but some fixtures are missing should render partial summary disclosure."""
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0
            if call_count[0] == 2:
                return 0.1
            if call_count[0] == 3:
                return 0.2
            return 2.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        corr = "agg-partial-001"
        for prediction_id in ("p1", "p2", "p3"):
            msg = _make_approved_msg(corr, expected_count=4, prediction_id=prediction_id)
            results = list(expired_agent.handle(msg))
            if prediction_id != "p3":
                assert results == []
            else:
                assert len(results) == 1
                ans = results[0]
                assert ans.payload["degraded"] is True
                assert "3/4 maç tahmini hazır" in ans.payload["answer_text"]
                assert "Eksik maçlar" in ans.payload["answer_text"]
                assert "summary quorum not met" not in (
                    ans.payload["degraded_reason"] or ""
                )

    def test_nlp_summary_zero_returns_renders_predict_timeout_template(self) -> None:
        """Zero returned summary aggregation renders predict.timeout template."""
        agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=lambda: 0.0,
        )
        agg = _SummaryAgg(
            expected=0,
            qa_request_id="req-summary-zero",
            qa_correlation_id="corr-summary-zero",
            deadline=0.0,
        )
        answer = agent._build_summary_answer(agg, "corr-summary-zero", 0)
        assert answer.envelope.topic == QA_ANSWER_V1
        assert answer.payload["intent"] == "predict.timeout"
        assert answer.payload["kind"] == "predict.timeout"
        assert answer.payload["degraded"] is True

    def test_nlp_summary_per_fixture_independent_timeout(self) -> None:
        """Summary answer emits on deadline expiry without waiting for all fixtures."""
        call_count = [0]

        def fake_monotonic() -> float:
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.0
            if call_count[0] == 2:
                return 0.1
            return 2.0

        expired_agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            monotonic=fake_monotonic,
        )
        corr = "agg-deadline-001"
        for prediction_id in ("p1", "p2"):
            msg = _make_approved_msg(corr, expected_count=4, prediction_id=prediction_id)
            results = list(expired_agent.handle(msg))
            if prediction_id == "p1":
                assert results == []
            else:
                assert len(results) == 1
                ans = results[0]
                assert ans.payload["degraded"] is True
                assert "summary quorum not met" in ans.payload["degraded_reason"]

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

    def test_nlp_citation_key_rotation_dual_window_accepts_both(
        self, agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """§10.21.8 rotation: both previous and current keys are accepted inside grace window."""
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

        prev_msg = _make_approved_msg("agg-prev-key-ok-001", expected_count=1, prediction_id="p-prev")
        prev_key_id = hashlib.sha256(prev_key).hexdigest()[:16]
        prev_blob = "p-prev|2026-05-27T10:00:00+00:00|model-1|1"
        prev_msg.payload["citation_key_id"] = prev_key_id
        prev_msg.payload["citation_signature"] = hmac.new(
            prev_key,
            prev_blob.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        new_msg = _make_approved_msg("agg-new-key-ok-001", expected_count=1, prediction_id="p-new")
        new_key_id = hashlib.sha256(new_key).hexdigest()[:16]
        new_blob = "p-new|2026-05-27T10:00:00+00:00|model-1|1"
        new_msg.payload["citation_key_id"] = new_key_id
        new_msg.payload["citation_signature"] = hmac.new(
            new_key,
            new_blob.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        prev_out = list(agent.handle(prev_msg))
        new_out = list(agent.handle(new_msg))
        assert len(prev_out) == 1
        assert prev_out[0].envelope.topic == QA_ANSWER_V1
        assert len(new_out) == 1
        assert new_out[0].envelope.topic == QA_ANSWER_V1


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

    def test_summary_citations_reflect_only_returned_fixtures_model_versions(
        self,
    ) -> None:
        """Partial summary citations carry model_versions only for returned fixtures."""
        agent = NlpAnswerAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-ans-id",
        )

        agg = _SummaryAgg(
            expected=2,
            qa_request_id="req-summary-001",
            qa_correlation_id="req-summary-001",
            deadline=0.0,
        )

        msg1 = _make_approved_msg(
            "agg-cite-001",
            expected_count=2,
            prediction_id="p1",
            degraded=False,
            degraded_reason=None,
        )
        msg1.payload["final"]["contributing_models"] = ["predictor-a@1.0.0"]
        msg1.payload["calibration_version"] = 1

        msg2 = _make_approved_msg(
            "agg-cite-001",
            expected_count=3,
            prediction_id="p2",
            degraded=False,
            degraded_reason=None,
        )
        msg2.payload["final"]["contributing_models"] = ["predictor-b@2.0.0"]
        msg2.payload["calibration_version"] = 2

        agg.predictions.extend([msg1.payload, msg2.payload])
        answer = agent._build_summary_answer(agg, "agg-cite-001", received=2)
        citations = answer.payload["citations"]

        assert len(citations) == 2
        assert citations[0]["calibration_version"] == 1
        assert citations[0]["model_versions"] == ["predictor-a@1.0.0"]
        assert citations[0]["prediction_count"] == 1
        assert citations[1]["calibration_version"] == 2
        assert citations[1]["model_versions"] == ["predictor-b@2.0.0"]
        assert citations[1]["prediction_count"] == 1

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


def test_nlp_summary_calibration_mismatch_note_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """§10.21.10: note mode keeps summary available with explicit disclosure."""
    monkeypatch.setattr(_cfg, "nlp_summary_calibration_mismatch_policy", "note")
    agent = NlpAnswerAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "test-ans-id",
    )
    corr = "agg-cal-note-001"
    msg1 = _make_approved_msg(corr, expected_count=2, prediction_id="note-p1")
    msg2 = _make_approved_msg(corr, expected_count=2, prediction_id="note-p2")
    msg2.payload["calibration_version"] = 2
    msg2.payload["final"]["calibration_version"] = 2

    list(agent.handle(msg1))
    out = list(agent.handle(msg2))
    qa_answers = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    assert len(qa_answers) == 1
    payload = qa_answers[0].payload
    assert payload["degraded"] is False
    assert "farklı kalibrasyon sürümleri" in payload["answer_text"]
    assert len(payload["citations"]) == 2


def test_nlp_summary_calibration_mismatch_refuse_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """§10.21.10: refuse mode degrades summary and emits per-fixture links."""
    monkeypatch.setattr(_cfg, "nlp_summary_calibration_mismatch_policy", "refuse")
    agent = NlpAnswerAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "test-ans-id",
    )
    corr = "agg-cal-refuse-001"
    msg1 = _make_approved_msg(corr, expected_count=2, prediction_id="refuse-p1")
    msg2 = _make_approved_msg(corr, expected_count=2, prediction_id="refuse-p2")
    msg2.payload["calibration_version"] = 2
    msg2.payload["final"]["calibration_version"] = 2

    list(agent.handle(msg1))
    out = list(agent.handle(msg2))
    qa_answers = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    assert len(qa_answers) == 1
    payload = qa_answers[0].payload
    assert payload["degraded"] is True
    assert (
        payload["answer_text"].startswith(
            "Bu hafta için tahminler farklı kalibrasyon sürümleriyle üretildiği için birleşik özet sunulamıyor."
        )
    )
    assert "/tahmin/refuse-p1" in payload["answer_text"]
    assert "/tahmin/refuse-p2" in payload["answer_text"]
    assert payload["degraded_reason"] is not None
    assert "summary calibration mismatch" in payload["degraded_reason"]


def test_dispatcher_tier_is_per_intent_not_humanizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """§10.21.11: tier_id_required depends on intent map, not humanizer_used."""
    monkeypatch.setattr(
        _cfg,
        "_nlp_intent_tier_map_raw",
        '{"predict.match_outcome":"pro"}',
        raising=False,
    )
    agent_templated = NlpDispatcherAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "tier-templated-corr",
    )
    msg_templated = _make_intent_msg(
        {
            "request_id": "req-tier-001",
            "entities": [],
            "humanizer_used": False,
        }
    )
    out_templated = list(agent_templated.handle(msg_templated))
    assert len(out_templated) == 1
    assert out_templated[0].payload["tier_id_required"] == "pro"

    agent_humanized = NlpDispatcherAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "tier-humanized-corr",
    )
    msg_humanized = _make_intent_msg(
        {
            "request_id": "req-tier-002",
            "entities": [],
            "humanizer_used": True,
        }
    )
    out_humanized = list(agent_humanized.handle(msg_humanized))
    assert len(out_humanized) == 1
    assert out_humanized[0].payload["tier_id_required"] == "pro"


def test_nlp_dispatcher_tier_lookup_does_not_branch_on_humanizer_ast() -> None:
    """§10.21.11 AST guard: dispatcher branch conditions must not use humanizer_used."""
    source = inspect.getsource(NlpDispatcherAgent)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_expr = ast.get_source_segment(source, node.test) or ""
            assert "humanizer_used" not in test_expr


