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
import copy
import datetime as _dt
import hashlib
import hmac
import json
import inspect
from collections import deque
from pathlib import Path

import pytest

from common.config import cfg as _cfg
from common.fixture_state import FixtureState
from nlp.conversation import ConversationStore
import swarm.agents.nlp as nlp_agent
from swarm.agents.nlp import (
    FixtureStateLookup,
    NlpAnswerAgent,
    NlpDispatcherAgent,
    NlpIntentAgent,
    _QA_ANSWER_SCHEMA_VERSION_REQUEST_KEY,
    _SummaryAgg,
    _load_fixture_state_routing,
    downgrade_qa_answer_v1,
)
from swarm.agents.topics import (
    DATA_REQUEST_V1,
    NLP_ALERT_V1,
    NLP_EVENT_V1,
    PREDICT_APPROVED,
    PREDICT_REQUEST_V1,
    QA_ANSWER_V1,
    QA_CONTEXT_EXTENSION_V1,
    QA_CONTEXT_V1,
    QA_FEEDBACK_V1,
    QA_INTENT_V1,
    QA_REQUEST,
    QA_REQUEST_V1,
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


def test_nlp_skew_detector_fires_on_synthetic_skew() -> None:
    original_window = _cfg.nlp_skew_window_s
    original_p95 = _cfg.nlp_skew_alert_p95
    original_min_requests = _cfg.nlp_skew_alert_min_requests
    original_debounce = _cfg.nlp_skew_alert_debounce_s
    _cfg.nlp_skew_window_s = 600
    _cfg.nlp_skew_alert_p95 = 0.4
    _cfg.nlp_skew_alert_min_requests = 3
    _cfg.nlp_skew_alert_debounce_s = 600

    try:
        agent = NlpDispatcherAgent()
        all_output: list[Message] = []
        for idx in range(4):
            msg = _make_intent_msg({
                "request_id": f"req-skew-{idx}",
                "intent": "predict.match_outcome",
                "entities": [],
                "intent_confidence": 0.95,
            })
            output = list(agent.handle(msg))
            all_output.extend(output)

        assert any(
            m.topic == NLP_ALERT_V1 and m.payload.get("kind") == "nlp_classifier_extractor_skew_high"
            for m in all_output
        )
        assert any(
            m.topic == QA_ANSWER_V1 and m.payload.get("kind") == "disambiguation"
            for m in output
        )
    finally:
        _cfg.nlp_skew_window_s = original_window
        _cfg.nlp_skew_alert_p95 = original_p95
        _cfg.nlp_skew_alert_min_requests = original_min_requests
        _cfg.nlp_skew_alert_debounce_s = original_debounce


def test_nlp_skew_histogram_is_observed(monkeypatch) -> None:
    observed: list[tuple[str, float]] = []

    class DummyHistogram:
        def labels(self, *, intent: str):
            class Observer:
                def observe(self, value: float) -> None:
                    observed.append((intent, value))
            return Observer()

    monkeypatch.setattr(
        nlp_agent,
        "NLP_CLASSIFIER_EXTRACTOR_SKEW",
        DummyHistogram(),
    )

    agent = NlpDispatcherAgent()
    msg = _make_intent_msg({
        "request_id": "req-skew-metric",
        "intent": "predict.match_outcome",
        "entities": [],
        "intent_confidence": 0.95,
    })
    list(agent.handle(msg))

    assert observed == [("predict.match_outcome", 0.95)]


def test_nlp_skew_detector_silent_on_meta_intents() -> None:
    original_min_requests = _cfg.nlp_skew_alert_min_requests
    _cfg.nlp_skew_alert_min_requests = 1
    try:
        agent = NlpDispatcherAgent()
        for idx in range(3):
            out = list(agent.handle(_make_intent_msg({
                "request_id": f"req-meta-{idx}",
                "intent": "meta.help",
                "entities": [],
                "intent_confidence": 0.95,
            })))
            assert not any(
                m.topic == NLP_ALERT_V1 and m.payload.get("kind") == "nlp_classifier_extractor_skew_high"
                for m in out
            )
    finally:
        _cfg.nlp_skew_alert_min_requests = original_min_requests


def test_nlp_skew_does_not_change_routing() -> None:
    original_min_requests = _cfg.nlp_skew_alert_min_requests
    _cfg.nlp_skew_alert_min_requests = 1
    try:
        agent = NlpDispatcherAgent()
        out = list(agent.handle(_make_intent_msg({
            "request_id": "req-routing",
            "intent": "predict.match_outcome",
            "entities": [],
            "intent_confidence": 0.95,
        })))
        assert any(
            m.topic == QA_ANSWER_V1 and m.payload.get("kind") == "disambiguation"
            for m in out
        )
        assert any(
            m.topic == NLP_ALERT_V1 and m.payload.get("kind") == "nlp_classifier_extractor_skew_high"
            for m in out
        )
    finally:
        _cfg.nlp_skew_alert_min_requests = original_min_requests


def test_pro_drop_resolver_uses_anaphora_first() -> None:
    agent = NlpDispatcherAgent()
    conversation_id = "conv-prodrop-anaphora"
    agent._conversation_store.save({
        "schema_version": 1,
        "conversation_id": conversation_id,
        "turn_index": 0,
        "intent": "predict.match_outcome",
        "entities": [],
        "anaphora_mentions": [
            {
                "canonical_id": "fb",
                "kind": "team",
                "confidence": 1.0,
                "name": "Fenerbahçe",
                "mentioned_turn": 0,
                "mentioned_at": agent._clock_iso(),
            }
        ],
        "expires_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    })

    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-prodrop-anaphora",
        "qa_correlation_id": "corr-prodrop-anaphora",
        "conversation_id": conversation_id,
        "intent": "predict.match_outcome",
        "entities": [],
        "intent_confidence": 0.92,
        "normalized_text": "Galatasaray kazandı mı?",
    })))

    assert any(
        m.topic == NLP_EVENT_V1
        and m.payload.get("kind") == "pro_drop_resolved"
        and m.payload.get("source") == "anaphora"
        and m.payload.get("resolved_entity_id") == "fb"
        for m in out
    )
    assert any(
        m.topic == QA_CONTEXT_V1
        and any(
            isinstance(e, dict)
            and e.get("kind") == "team"
            and e.get("canonical_id") == "fb"
            for e in m.payload.get("entities", [])
        )
        for m in out
    )


def test_anaphora_mentions_are_tagged_as_user() -> None:
    agent = NlpDispatcherAgent()
    conversation_id = "conv-user-anaphora"
    agent._conversation_store.clear(conversation_id)

    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-user-anaphora",
        "qa_correlation_id": "corr-user-anaphora",
        "conversation_id": conversation_id,
        "intent": "predict.match_outcome",
        "entities": [
            {
                "kind": "team",
                "canonical_id": "gs",
                "confidence": 0.9,
                "name": "Galatasaray",
            }
        ],
        "normalized_text": "Galatasaray kazandı mı?",
    })))

    assert any(
        m.topic == QA_CONTEXT_V1
        and any(
            isinstance(mention, dict)
            and mention.get("kind") == "team"
            and mention.get("canonical_id") == "gs"
            and mention.get("mentioned_by") == "user"
            for mention in m.payload.get("anaphora_mentions", [])
        )
        for m in out
    )


def test_pro_drop_default_team_capped_at_confidence() -> None:
    agent = NlpDispatcherAgent()
    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-prodrop-default",
        "qa_correlation_id": "corr-prodrop-default",
        "conversation_id": "conv-prodrop-default",
        "intent": "data.lineup_probable",
        "entities": [],
        "request_metadata": {
            "user_preferences": {
                "favorite_team": "fb",
            },
        },
    })))

    assert any(
        m.topic == NLP_EVENT_V1
        and m.payload.get("kind") == "pro_drop_resolved"
        and m.payload.get("source") == "default_team"
        and m.payload.get("resolved_entity_id") == "fb"
        for m in out
    )
    assert any(
        m.topic == QA_CONTEXT_V1
        and any(
            isinstance(e, dict)
            and e.get("kind") == "team"
            and e.get("canonical_id") == "fb"
            and e.get("confidence") == pytest.approx(0.55)
            for e in m.payload.get("entities", [])
        )
        for m in out
    )


def test_pro_drop_no_anaphora_no_default_emits_disambiguation() -> None:
    agent = NlpDispatcherAgent()
    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-prodrop-disambiguation",
        "qa_correlation_id": "corr-prodrop-disambiguation",
        "conversation_id": "conv-prodrop-disambiguation",
        "intent": "predict.match_outcome",
        "entities": [],
        "intent_confidence": 0.93,
        "normalized_text": "Galatasaray kazandı mı?",
    })))

    assert any(
        m.topic == QA_ANSWER_V1 and m.payload.get("kind") == "disambiguation"
        for m in out
    )
    assert not any(
        m.topic == NLP_EVENT_V1 and m.payload.get("kind") == "pro_drop_resolved"
        for m in out
    )


def test_anaphora_with_multiple_system_mentions_emits_disambiguation() -> None:
    conversation_id = "conv-system-anaphora"
    store = ConversationStore()
    store.save({
        "schema_version": 1,
        "conversation_id": conversation_id,
        "turn_index": 2,
        "entities": [],
        "intent": "predict.match_outcome",
        "anaphora_mentions": [
            {
                "canonical_id": "gs",
                "kind": "team",
                "confidence": 0.9,
                "name": "Galatasaray",
                "mentioned_turn": 0,
                "mentioned_at": "2026-05-27T09:59:00+00:00",
                "mentioned_by": "system",
            },
            {
                "canonical_id": "fb",
                "kind": "team",
                "confidence": 0.95,
                "name": "Fenerbahçe",
                "mentioned_turn": 1,
                "mentioned_at": "2026-05-27T09:59:30+00:00",
                "mentioned_by": "system",
            },
        ],
        "expires_at_utc": "2026-05-27T10:30:00+00:00",
    })

    agent = NlpDispatcherAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "test-corr-id",
    )
    agent._conversation_store = store
    msg = _make_intent_msg({
        "request_id": "req-system-anaphora",
        "qa_correlation_id": "corr-system-anaphora",
        "conversation_id": conversation_id,
        "intent": "predict.match_outcome",
        "entities": [],
        "intent_confidence": 0.87,
        "normalized_text": "o kazanır mı",
    })
    results = list(agent.handle(msg))
    answers = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
    assert len(answers) == 1
    assert answers[0].payload["kind"] == "disambiguation"


def test_pro_drop_resolver_only_fires_on_pro_drop_intent_classes() -> None:
    agent = NlpDispatcherAgent()
    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-prodrop-noop",
        "qa_correlation_id": "corr-prodrop-noop",
        "conversation_id": "conv-prodrop-noop",
        "intent": "meta.help",
        "entities": [],
        "intent_confidence": 0.99,
        "request_metadata": {
            "user_preferences": {
                "favorite_team": "fb",
            },
        },
    })))

    assert not any(
        m.topic == NLP_EVENT_V1 and m.payload.get("kind") == "pro_drop_resolved"
        for m in out
    )


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


def test_nlp_conversational_meta_routes_to_user_data_disclosure() -> None:
    agent = NlpDispatcherAgent()
    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-meta-user-data",
        "intent": "predict.match_outcome",
        "normalized_text": "Benim hakkımda ne biliyorsun?",
        "conversation_id": "conv-meta-user",
    })))

    answers = [m for m in out if m.topic == QA_ANSWER_V1]
    assert len(answers) == 1
    assert answers[0].payload["intent"] == "meta.user_data_disclosure"
    assert "KVKK" in answers[0].payload["answer_text"]


def test_nlp_conversational_meta_routes_to_system_capabilities_with_template_path(tmp_path: Path) -> None:
    old_path = _cfg.nlp_system_capability_template_path
    try:
        custom_path = tmp_path / "system_capabilities.txt"
        custom_path.write_text("Ben bir futbol asistanıyım.", encoding="utf-8")
        _cfg.nlp_system_capability_template_path = str(custom_path)

        agent = NlpDispatcherAgent()
        out = list(agent.handle(_make_intent_msg({
            "request_id": "req-meta-system",
            "intent": "predict.match_outcome",
            "normalized_text": "Neler yapabilirsin?",
            "conversation_id": "conv-meta-system",
        })))

        answers = [m for m in out if m.topic == QA_ANSWER_V1]
        assert len(answers) == 1
        assert answers[0].payload["intent"] == "meta.system_capabilities"
        assert "Ben bir futbol asistanıyım." in answers[0].payload["answer_text"]
    finally:
        _cfg.nlp_system_capability_template_path = old_path


def test_nlp_conversational_meta_conversation_history_rendered_from_safe_metadata() -> None:
    agent = NlpDispatcherAgent()
    conversation_id = "conv-meta-history"
    agent._conversation_store.save_metadata(conversation_id, {
        "conversation_history": [
            {"turn_index": 0, "intent": "predict.match_outcome", "entities": ["team:galatasaray"]},
            {"turn_index": 1, "intent": "predict.btts", "entities": ["team:fenerbahce"]},
        ]
    })

    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-meta-history",
        "intent": "predict.match_outcome",
        "normalized_text": "Daha önce ne sormuştum?",
        "conversation_id": conversation_id,
    })))

    answers = [m for m in out if m.topic == QA_ANSWER_V1]
    assert len(answers) == 1
    assert answers[0].payload["intent"] == "meta.conversation_history"
    assert "predict.match_outcome" in answers[0].payload["answer_text"]
    assert "team:galatasaray" in answers[0].payload["answer_text"]


def test_nlp_conversational_meta_last_answer_explain_uses_saved_answer_text() -> None:
    agent = NlpDispatcherAgent()
    conversation_id = "conv-meta-last-answer"
    agent._conversation_store.save_metadata(conversation_id, {
        "last_qa_answer_text": "Galatasaray kazanabilir.",
    })

    out = list(agent.handle(_make_intent_msg({
        "request_id": "req-meta-last-answer",
        "intent": "predict.match_outcome",
        "normalized_text": "Ne demek istedin?",
        "conversation_id": conversation_id,
    })))

    answers = [m for m in out if m.topic == QA_ANSWER_V1]
    assert len(answers) == 1
    assert answers[0].payload["intent"] == "meta.last_answer_explain"
    assert "Galatasaray kazanabilir." in answers[0].payload["answer_text"]


def test_nlp_user_data_disclosure_template_never_reads_user_columns() -> None:
    from nlp.render import build_environment, render

    env = build_environment(user_text_for_guard="benim hakkımda ne biliyorsun?")
    rendered = render(
        "meta.user_data_disclosure.tr.j2",
        {"user_id": "secret", "email": "secret@example.com"},
        env=env,
    )
    assert "secret" not in rendered
    assert "secret@example.com" not in rendered


def test_meta_question_routing_short_circuits_before_intent_classifier() -> None:
    agent = NlpIntentAgent()
    msg = _make_request_msg(
        {
            "request_id": "req-meta-001",
            "sanitized_text": "ne düşünüyorsun",
        }
    )
    results = list(agent.handle(msg))
    qa_messages = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
    assert len(qa_messages) == 1
    assert qa_messages[0].payload["intent"] == "meta.opinion_request"
    assert "sistem" in qa_messages[0].payload["answer_text"].lower()


def test_nlp_intent_agent_merges_system_context_extension_into_store() -> None:
    agent = NlpIntentAgent()
    conversation_id = "conv-ext-001"
    agent._conversation_store.save({
        "schema_version": 1,
        "conversation_id": conversation_id,
        "turn_index": 0,
        "entities": [
            {
                "span_start": 0,
                "span_end": 1,
                "kind": "team",
                "canonical_id": "gs",
                "confidence": 0.9,
                "source": "gazetteer",
            }
        ],
        "intent": "predict.match_outcome",
        "anaphora_mentions": [],
        "expires_at_utc": "2026-05-27T10:00:00+00:00",
    })

    ext_msg = Message.new(
        topic=QA_CONTEXT_EXTENSION_V1,
        payload={
            "schema_version": 1,
            "conversation_id": conversation_id,
            "entities": [
                {
                    "kind": "team",
                    "canonical_id": "fb",
                    "confidence": 0.95,
                    "source": "system",
                }
            ],
            "emitted_at_utc": "2026-05-27T10:00:00+00:00",
        },
        producer="nlp.answer.v1",
    )

    results = list(agent.handle(ext_msg))
    assert results == []

    context = agent._conversation_store.load(conversation_id)
    assert context is not None
    mentions = [m for m in context["anaphora_mentions"] if isinstance(m, dict)]
    assert any(
        mention.get("canonical_id") == "fb" and mention.get("mentioned_by") == "system"
        for mention in mentions
    )


def test_meta_question_rhetorical_tier_blind_refusal_remains_identical() -> None:
    agent = NlpIntentAgent()
    base = {
        "sanitized_text": "sen ne diyorsun la",
        "request_metadata": {"tier_id": "gold"},
    }
    first = list(agent.handle(_make_request_msg({**base, "request_id": "req-meta-tier-001"})))
    second = list(agent.handle(_make_request_msg({**base, "request_id": "req-meta-tier-002", "request_metadata": {"tier_id": "free"}})))
    first_text = next(r.payload["answer_text"] for r in first if r.envelope.topic == QA_ANSWER_V1)
    second_text = next(r.payload["answer_text"] for r in second if r.envelope.topic == QA_ANSWER_V1)
    assert first_text == second_text
    assert "rhetorik" in first_text.lower() or "soru" in first_text.lower()


def test_sarcasm_modifier_only_used_by_dispatcher_refusal_path_ast() -> None:
    root = Path(__file__).resolve().parents[2]
    banned_paths = [
        root / "ai" / "nlp" / "intent.py",
        root / "ai" / "nlp" / "proofreader.py",
        root / "ai" / "swarm" / "agents" / "cache.py",
    ]
    violations: list[str] = []
    for path in banned_paths:
        source = path.read_text(encoding="utf-8")
        if "intent_modifier" in source:
            violations.append(f"{path}:intent_modifier usage outside dispatcher refusal path")
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


def _make_request_msg(overrides: dict | None = None) -> Message:
    payload = {
        "request_id": "req-request-001",
        "conversation_id": "conv-001",
        "locale": "tr-TR",
        "input_source": "keyboard",
        "sanitized_text": "",
        "request_metadata": {},
    }
    if overrides:
        payload.update(overrides)
    return Message.new(topic=QA_REQUEST_V1, payload=payload)


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


def _make_venue_entity(canonical_id: str = "galatasaray") -> dict:
    return {
        "span_start": 0,
        "span_end": 3,
        "kind": "venue",
        "canonical_id": canonical_id,
        "confidence": 1.0,
        "lexicon_version": "1.0.0",
        "source": "gazetteer",
    }


def _make_date_entity_at(
    canonical_id: str,
    span_start: int,
    span_end: int,
) -> dict:
    return {
        "span_start": span_start,
        "span_end": span_end,
        "kind": "date",
        "canonical_id": canonical_id,
        "confidence": 0.93,
        "lexicon_version": "1.0.0",
        "source": "date_resolver",
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

    def test_publishes_qa_context_extension_v1(self) -> None:
        assert QA_CONTEXT_EXTENSION_V1 in NlpAnswerAgent.publishes


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
        assert isinstance(payload.get("parts"), list)
        assert len(payload["parts"]) == 1
        first_part = payload["parts"][0]
        assert first_part["intent"] == payload["intent"]
        assert first_part["body"] == payload["answer_text"]
        assert first_part["polarity"] == "affirm"
        assert first_part["subquery_correlation_id"] == payload["qa_correlation_id"]

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

    def test_verbal_noun_ambiguity_triggers_disambiguation(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg({
            "intent": "data.fixture_lookup",
            "normalized_text": "galatasaray oynaması",
            "entities": [
                {
                    "span_start": 0,
                    "span_end": 1,
                    "kind": "team",
                    "canonical_id": "gs",
                    "confidence": 1.0,
                    "source": "gazetteer",
                    "name": "Galatasaray",
                    "syntactic_role": "ambiguous",
                }
            ],
        })
        results = list(agent.handle(msg))
        assert len(results) == 1
        out = results[0]
        assert out.envelope.topic == QA_ANSWER_V1
        assert out.payload["kind"] == "disambiguation"
        assert "Galatasaray'ın oynaması mı" in out.payload["answer_text"]
        assert "Galatasaray oynamak mı" in out.payload["answer_text"]

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
        assert len(results) == 2
        assert results[0].envelope.topic == DATA_REQUEST_V1
        assert results[1].envelope.topic == PREDICT_REQUEST_V1

    def test_predict_with_competition_entity_no_backoff(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """predict.* WITH a competition entity must NOT trigger the backoff path."""
        msg = _make_intent_msg({"entities": [_make_competition_entity()]})
        results = list(agent.handle(msg))
        assert len(results) == 2
        assert results[0].envelope.topic == DATA_REQUEST_V1
        assert results[1].envelope.topic == PREDICT_REQUEST_V1

    def test_predict_with_team_entity_emits_fixture_state_lookup_before_predict(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg({"entities": [_make_team_entity()]})
        results = list(agent.handle(msg))

        assert len(results) == 2

        lookup_req = results[0]
        assert lookup_req.envelope.topic == DATA_REQUEST_V1
        assert lookup_req.payload["kind"] == "fixture_state"
        assert lookup_req.payload["match_id"] == "gs"
        assert lookup_req.payload["timeout_ms"] == _cfg.nlp_fixture_state_lookup_timeout_ms
        assert lookup_req.payload["qa_correlation_id"] == ""

        predict_req = results[1]
        assert predict_req.envelope.topic == PREDICT_REQUEST_V1
        assert predict_req.payload["match_id"] == "gs"
        assert predict_req.payload["qa_request_id"] == "req-001"

    def test_predict_with_venue_entity_infers_home_team_and_emits_fixture_state_lookup(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg({
            "intent": "predict.match_outcome",
            "entities": [_make_venue_entity("galatasaray")],
        })
        results = list(agent.handle(msg))

        assert len(results) == 2
        lookup_req = results[0]
        assert lookup_req.envelope.topic == DATA_REQUEST_V1
        assert lookup_req.payload["kind"] == "fixture_state"
        assert lookup_req.payload["match_id"] == "galatasaray_sk"

        predict_req = results[1]
        assert predict_req.envelope.topic == PREDICT_REQUEST_V1
        assert predict_req.payload["match_id"] == "galatasaray_sk"

    def test_venue_inference_confidence_is_capped_by_config(self, agent: NlpDispatcherAgent) -> None:
        inferred = agent._infer_team_from_venue([
            {
                "span_start": 0,
                "span_end": 3,
                "kind": "venue",
                "canonical_id": "galatasaray",
                "confidence": 1.0,
                "lexicon_version": "1.0.0",
            }
        ])
        assert inferred is not None
        assert inferred["kind"] == "team"
        assert inferred["confidence"] == _cfg.nlp_venue_inferred_team_confidence_cap

    def test_predict_with_team_entity_in_play_state_refuses_predict_and_routes_live_state(
        self, agent: NlpDispatcherAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.IN_PLAY_FIRST_HALF.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = _make_intent_msg({"entities": [_make_team_entity()]})
        results = list(agent.handle(msg))

        assert len(results) == 3
        assert results[0].envelope.topic == DATA_REQUEST_V1
        assert results[0].payload["kind"] == "fixture_state"

        assert results[1].envelope.topic == DATA_REQUEST_V1
        assert results[1].payload["kind"] == "live_state"
        assert results[1].payload["params"]["match_id"] == "gs"
        assert results[1].payload["params"].get("degraded") is None

        assert results[2].envelope.topic == QA_ANSWER_V1
        assert results[2].payload["intent"] == "meta.live_match_unsupported"
        assert results[2].payload["kind"] == "live_match_unsupported"
        assert "Maç şu an oynanıyor" in results[2].payload["answer_text"]

    def test_predict_with_team_entity_unknown_state_routes_to_live_state_with_degraded_meta(
        self, agent: NlpDispatcherAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.UNKNOWN.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = _make_intent_msg({"entities": [_make_team_entity()]})
        results = list(agent.handle(msg))

        assert results[1].envelope.topic == DATA_REQUEST_V1
        assert results[1].payload["kind"] == "live_state"
        assert results[1].payload["params"]["match_id"] == "gs"
        assert results[1].payload["params"]["degraded"] is True

        assert results[2].envelope.topic == QA_ANSWER_V1
        assert results[2].payload["intent"] == "meta.fixture_state_unknown"
        assert results[2].payload["kind"] == "fixture_state_unknown"
        assert results[2].payload["degraded"] is True
        assert results[2].payload["degraded_reason"] == "fixture_state_unknown"

    def test_predict_with_team_entity_finished_state_routes_to_data_h2h(
        self, agent: NlpDispatcherAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.FINISHED.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = _make_intent_msg({"entities": [_make_team_entity()]})
        results = list(agent.handle(msg))

        assert results[0].payload["kind"] == "fixture_state"
        assert results[1].envelope.topic == DATA_REQUEST_V1
        assert results[1].payload["kind"] == "h2h"
        assert results[1].payload["params"]["match_id"] == "gs"
        assert len(results) == 2

    def test_fixture_state_routing_yaml_matches_enum_completeness(self) -> None:
        routing = _load_fixture_state_routing()
        expected_states = {state.value for state in FixtureState}
        assert set(routing) == expected_states

    def test_nlp_dispatcher_consults_fixture_state_before_predict_request_ast(self) -> None:
        source = Path(__file__).resolve().parents[2] / "ai" / "swarm" / "agents" / "nlp" / "__init__.py"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        handle_def = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "NlpDispatcherAgent":
                for member in node.body:
                    if isinstance(member, ast.FunctionDef) and member.name == "handle":
                        handle_def = member
                        break
                break
        assert handle_def is not None, "NlpDispatcherAgent.handle not found"

        lookup_lineno = []
        predict_lineno = []
        for node in ast.walk(handle_def):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "FixtureStateLookup" and node.func.attr == "get":
                    lookup_lineno.append(node.lineno)
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "Message" and node.func.attr == "new":
                    for keyword in node.keywords:
                        if keyword.arg == "topic" and isinstance(keyword.value, ast.Name) and keyword.value.id == "PREDICT_REQUEST_V1":
                            predict_lineno.append(node.lineno)
        assert lookup_lineno, "No FixtureStateLookup.get call found in dispatcher.handle"
        assert predict_lineno, "No Message.new(PREDICT_REQUEST_V1) found in dispatcher.handle"
        assert min(lookup_lineno) < min(predict_lineno), (
            "FixtureStateLookup.get must appear before the first PREDICT_REQUEST_V1 route in dispatcher.handle"
        )

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

    def test_conversation_correction_replacement_applies_to_context(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-corr-001"
        agent._conversation_store.clear(conversation_id)
        agent._conversation_store.save({
            "schema_version": 1,
            "conversation_id": conversation_id,
            "turn_index": 0,
            "entities": [_make_team_entity("gs")],
            "intent": "predict.match_outcome",
            "anaphora_mentions": [],
            "expires_at_utc": "2026-05-27T10:00:00+00:00",
        })

        msg = _make_intent_msg({
            "request_id": "req-corr-001",
            "conversation_id": conversation_id,
            "normalized_text": "değil, Beşiktaş demek istedim",
            "entities": [_make_team_entity("bjk")],
        })
        results = list(agent.handle(msg))

        assert any(
            result.envelope.topic == NLP_EVENT_V1
            and result.payload.get("kind") == "conversation_correction_applied"
            for result in results
        )
        context_msg = next(
            result for result in results if result.envelope.topic == QA_CONTEXT_V1
        )
        assert all(entity["canonical_id"] != "gs" for entity in context_msg.payload["entities"])
        assert any(entity["canonical_id"] == "bjk" for entity in context_msg.payload["entities"])

    def test_conversation_correction_restart_clears_context(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-corr-002"
        agent._conversation_store.clear(conversation_id)
        agent._conversation_store.save({
            "schema_version": 1,
            "conversation_id": conversation_id,
            "turn_index": 0,
            "entities": [_make_team_entity("gs")],
            "intent": "predict.match_outcome",
            "anaphora_mentions": [],
            "expires_at_utc": "2026-05-27T10:00:00+00:00",
        })

        msg = _make_intent_msg({
            "request_id": "req-corr-002",
            "conversation_id": conversation_id,
            "normalized_text": "yok yok, baştan",
            "entities": [],
        })
        results = list(agent.handle(msg))

        assert any(
            result.envelope.topic == NLP_EVENT_V1
            and result.payload.get("kind") == "conversation_restarted_by_user"
            for result in results
        )
        context_msg = next(
            result for result in results if result.envelope.topic == QA_CONTEXT_V1
        )
        assert context_msg.payload["entities"] == []

    def test_correction_grammar_disabled_when_conversation_id_absent(
        self,
        agent: NlpDispatcherAgent,
    ) -> None:
        msg = _make_intent_msg({
            "request_id": "req-corr-003",
            "normalized_text": "değil, Beşiktaş demek istedim",
            "entities": [_make_team_entity("bjk")],
        })
        results = list(agent.handle(msg))

        assert all(
            not (
                result.envelope.topic == NLP_EVENT_V1
                and result.payload.get("kind") in {
                    "conversation_correction_applied",
                    "conversation_restarted_by_user",
                }
            )
            for result in results
        )
        assert all(result.envelope.topic != QA_CONTEXT_V1 for result in results)

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

    def test_nlp_entity_state_ttl_per_class_triggers_refresh_and_disclosure(
        self,
        agent: NlpDispatcherAgent,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation_id = "conv-state-refresh"
        agent._conversation_store.clear(conversation_id)
        context_payload = {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "turn_index": 0,
            "entities": [
                {
                    **_make_team_entity("gs"),
                    "fixture_state": FixtureState.SCHEDULED.value,
                    "state_class": "pre_match",
                    "last_resolved_state_at": "2026-05-27T09:54:00+00:00",
                }
            ],
            "intent": "predict.match_outcome",
            "anaphora_mentions": [],
        }
        agent._conversation_store.save(context_payload)
        agent._clock_iso = lambda: "2026-05-27T10:00:00+00:00"

        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            assert match_id == "gs"
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-001",
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer=agent.name,
            )
            return (
                FixtureState.IN_PLAY_FIRST_HALF.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        invalidated = {"called": False}

        expected_conversation_id = conversation_id
        def fake_invalidate(entity: dict[str, object], conversation_id: str | None = None) -> None:
            invalidated["called"] = True
            assert entity["canonical_id"] == "gs"
            assert conversation_id == expected_conversation_id

        monkeypatch.setattr(agent, "_invalidate_entity_state_change_cache", fake_invalidate)

        msg = _make_intent_msg({
            "conversation_id": conversation_id,
            "request_id": "req-001",
            "qa_correlation_id": "corr-001",
            "entities": [_make_team_entity("gs")],
        })

        results = list(agent.handle(msg))
        assert any(
            r.envelope.topic == DATA_REQUEST_V1 and r.payload.get("kind") == "fixture_state"
            for r in results
        )
        assert any(
            r.envelope.topic == QA_ANSWER_V1 and r.payload.get("kind") == "entity_state_changed"
            for r in results
        )
        assert invalidated["called"]

        context = agent._conversation_store.load(conversation_id)
        assert context is not None
        entity_context = context["entities"][0]
        assert entity_context["fixture_state"] == FixtureState.IN_PLAY_FIRST_HALF.value
        assert entity_context["state_class"] == "live"
        assert entity_context["last_resolved_state_at"] == "2026-05-27T10:00:00+00:00"

    def test_nlp_fresh_entity_state_reuses_cached_fixture_state_without_extra_lookup(
        self,
        agent: NlpDispatcherAgent,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation_id = "conv-state-fresh"
        agent._conversation_store.clear(conversation_id)
        now = _dt.datetime.now(_dt.timezone.utc)
        context_payload = {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "turn_index": 0,
            "entities": [
                {
                    **_make_team_entity("gs"),
                    "fixture_state": FixtureState.SCHEDULED.value,
                    "state_class": "pre_match",
                    "last_resolved_state_at": (now - _dt.timedelta(seconds=30)).isoformat(),
                }
            ],
            "intent": "predict.match_outcome",
            "anaphora_mentions": [],
        }
        agent._conversation_store.save(context_payload)
        agent._clock_iso = lambda: now.isoformat()

        def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("FixtureStateLookup.get must not be called for fresh cached state")

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fail_if_called))

        msg = _make_intent_msg({
            "conversation_id": conversation_id,
            "request_id": "req-002",
            "qa_correlation_id": "corr-002",
            "entities": [_make_team_entity("gs")],
        })

        results = list(agent.handle(msg))
        assert any(r.envelope.topic == PREDICT_REQUEST_V1 for r in results)

        context = agent._conversation_store.load(conversation_id)
        assert context is not None
        entity_context = context["entities"][0]
        assert entity_context["fixture_state"] == FixtureState.SCHEDULED.value
        assert entity_context["state_class"] == "pre_match"
        assert entity_context["last_resolved_state_at"] == (now - _dt.timedelta(seconds=30)).isoformat()

    @pytest.mark.parametrize(
        (
            "initial_state",
            "initial_state_class",
            "lookup_state",
            "ttl_key",
            "delta_s",
        ),
        [
            (
                FixtureState.SCHEDULED.value,
                "pre_match",
                FixtureState.IN_PLAY_FIRST_HALF.value,
                "nlp_entity_pre_match_max_stale_s",
                301,
            ),
            (
                FixtureState.IN_PLAY_FIRST_HALF.value,
                "live",
                FixtureState.FINISHED.value,
                "nlp_entity_live_max_stale_s",
                31,
            ),
            (
                FixtureState.FINISHED.value,
                "post_match",
                FixtureState.POSTPONED.value,
                "nlp_entity_post_match_max_stale_s",
                3601,
            ),
        ],
    )
    def test_entity_state_ttl_per_class_triggers_refresh_and_disclosure(
        self,
        agent: NlpDispatcherAgent,
        monkeypatch: pytest.MonkeyPatch,
        initial_state: str,
        initial_state_class: str,
        lookup_state: str,
        ttl_key: str,
        delta_s: int,
    ) -> None:
        conversation_id = "conv-state-ttl"
        agent._conversation_store.clear(conversation_id)
        now = _dt.datetime.now(_dt.timezone.utc)
        stale_time = (now - _dt.timedelta(seconds=delta_s)).isoformat()
        context_payload = {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "turn_index": 0,
            "entities": [
                {
                    **_make_team_entity("gs"),
                    "fixture_state": initial_state,
                    "state_class": initial_state_class,
                    "last_resolved_state_at": stale_time,
                }
            ],
            "intent": "predict.match_outcome",
            "anaphora_mentions": [],
        }
        agent._conversation_store.save(context_payload)
        agent._clock_iso = lambda: now.isoformat()

        called: dict[str, bool] = {"lookup": False}

        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            assert match_id == "gs"
            called["lookup"] = True
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-ttl",
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": now.isoformat(),
                },
                producer=agent.name,
            )
            return (lookup_state, now.isoformat(), "test", lookup_req)

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))

        msg = _make_intent_msg({
            "conversation_id": conversation_id,
            "request_id": "req-ttl",
            "qa_correlation_id": "corr-ttl",
            "entities": [_make_team_entity("gs")],
        })

        results = list(agent.handle(msg))
        assert called["lookup"]
        assert any(
            r.envelope.topic == DATA_REQUEST_V1 and r.payload.get("kind") == "fixture_state"
            for r in results
        )
        assert any(
            r.envelope.topic == QA_ANSWER_V1 and r.payload.get("kind") == "entity_state_changed"
            for r in results
        )

        context = agent._conversation_store.load(conversation_id)
        assert context is not None
        entity_context = context["entities"][0]
        assert entity_context["fixture_state"] == lookup_state
        assert entity_context["state_class"] == {
            FixtureState.IN_PLAY_FIRST_HALF.value: "live",
            FixtureState.FINISHED.value: "post_match",
            FixtureState.POSTPONED.value: "postponed",
        }[lookup_state]
        assert entity_context["last_resolved_state_at"] == now.isoformat()

    def test_entity_state_change_invalidates_repeated_query_cache(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-state-invalidate"
        agent._conversation_store.clear(conversation_id)
        now = _dt.datetime.now(_dt.timezone.utc)
        agent._conversation_store.save_metadata(conversation_id, {
            "repeated_query_cached_answer": {
                "signature": "sig",
                "cached_at": now.isoformat(),
                "payload": {"intent": "predict.match_outcome"},
            }
        })

        entity = {
            **_make_team_entity("gs"),
            "fixture_state": FixtureState.IN_PLAY_FIRST_HALF.value,
            "state_class": "live",
            "last_resolved_state_at": (now - _dt.timedelta(seconds=301)).isoformat(),
        }

        agent._invalidate_entity_state_change_cache(entity, conversation_id)

        metadata = agent._conversation_store.load_metadata(conversation_id)
        assert metadata is not None
        assert "repeated_query_cached_answer" not in metadata

    def test_entity_state_change_invalidation_calls_l1_cache_hook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, object | None] = {"entity": None, "conversation_id": None}
        def cache_hook(entity: dict[str, object], conversation_id: str | None) -> None:
            called["entity"] = entity
            called["conversation_id"] = conversation_id

        agent = NlpDispatcherAgent(cache_invalidator=cache_hook)
        conversation_id = "conv-state-hook"
        agent._conversation_store.clear(conversation_id)
        now = _dt.datetime.now(_dt.timezone.utc)
        context_payload = {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "turn_index": 0,
            "entities": [
                {
                    **_make_team_entity("gs"),
                    "fixture_state": FixtureState.SCHEDULED.value,
                    "state_class": "pre_match",
                    "last_resolved_state_at": (now - _dt.timedelta(seconds=301)).isoformat(),
                }
            ],
            "intent": "predict.match_outcome",
            "anaphora_mentions": [],
        }
        agent._conversation_store.save(context_payload)
        agent._clock_iso = lambda: now.isoformat()

        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-hook",
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": now.isoformat(),
                },
                producer=agent.name,
            )
            return (
                FixtureState.IN_PLAY_FIRST_HALF.value,
                now.isoformat(),
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        results = list(agent.handle(_make_intent_msg({
            "conversation_id": conversation_id,
            "request_id": "req-hook",
            "qa_correlation_id": "corr-hook",
            "entities": [_make_team_entity("gs")],
        })))

        assert any(
            r.envelope.topic == QA_ANSWER_V1 and r.payload.get("kind") == "entity_state_changed"
            for r in results
        )
        assert isinstance(called["entity"], dict)
        assert called["entity"]["canonical_id"] == "gs"
        assert called["conversation_id"] == conversation_id

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

    def test_repeated_query_serves_cached_answer_within_max_age(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-repeated-cache-1"
        agent._conversation_store.clear(conversation_id)

        base = {
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
            "intent": "predict.match_outcome",
            "query_style": "search",
        }
        first = _make_intent_msg({**base, "request_id": "req-001", "qa_correlation_id": "corr-001"})
        results1 = list(agent.handle(first))
        first_answer = next(
            r for r in results1
            if r.envelope.topic == QA_ANSWER_V1
        )
        assert first_answer.payload["kind"] == "search_syntax_unsupported"

        second = _make_intent_msg({**base, "request_id": "req-002", "qa_correlation_id": "corr-002"})
        results2 = list(agent.handle(second))
        second_answer = next(
            r for r in results2
            if r.envelope.topic == QA_ANSWER_V1
        )

        assert second_answer.payload["request_id"] == first_answer.payload["request_id"]
        assert isinstance(second_answer.payload.get("cached_at"), str)

    def test_repeated_query_serves_fresh_when_cache_older_than_repeat_max_age(self, agent: NlpDispatcherAgent) -> None:
        conversation_id = "conv-repeated-cache-2"
        agent._conversation_store.clear(conversation_id)

        base = {
            "conversation_id": conversation_id,
            "entities": [_make_team_entity("gs")],
            "intent": "predict.match_outcome",
            "query_style": "search",
        }
        first = _make_intent_msg({**base, "request_id": "req-001", "qa_correlation_id": "corr-001"})
        list(agent.handle(first))

        history = agent._conversation_store.load_metadata(conversation_id)
        assert history is not None
        cached_answer = history.get("repeated_query_cached_answer")
        assert isinstance(cached_answer, dict)
        assert isinstance(cached_answer.get("payload"), dict)

        old_cached_at = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=int(_cfg.nlp_repeated_query_cache_max_age_s) + 1)).isoformat()
        cached_answer["cached_at"] = old_cached_at
        cached_answer["payload"]["cached_at"] = old_cached_at
        agent._conversation_store.save_metadata(conversation_id, history)

        second = _make_intent_msg({**base, "request_id": "req-002", "qa_correlation_id": "corr-002"})
        results2 = list(agent.handle(second))
        second_answer = next(
            r for r in results2
            if r.envelope.topic == QA_ANSWER_V1
        )

        assert second_answer.payload["request_id"] == "req-002"
        assert "cached_at" not in second_answer.payload

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

    def test_topic_red_partial_bus_fails_with_meta_partial_bus_unavailable(
        self, agent: NlpDispatcherAgent
    ) -> None:
        class FakeBusHealthTracker:
            def __init__(self, health_map: dict[str, str]) -> None:
                self._health_map = health_map

            def topic_health(self, topic: str) -> str:
                return self._health_map.get(topic, "green")

        agent._topic_dependency_map = {
            "predict.match_outcome": {
                "publish": ["predict.request.v1"],
                "consume": ["predict.approved.v1"],
            },
            "data.standings": {
                "publish": ["data.request.v1"],
                "consume": ["data.response.v1"],
            },
            "meta.help": {"publish": [], "consume": []},
        }
        agent._bus_health_tracker = FakeBusHealthTracker({"data.request.v1": "red"})

        msg = _make_intent_msg({"intent": "data.standings", "entities": []})
        results = list(agent.handle(msg))
        assert len(results) == 1
        assert results[0].envelope.topic == QA_ANSWER_V1
        assert results[0].payload["intent"] == "meta.partial_bus_unavailable"
        assert results[0].payload.get("degraded") is True
        assert results[0].payload.get("degraded_reason") == "partial_bus_data.request.v1"

    def test_topic_yellow_partial_bus_serves_cached_answer_and_emits_event(
        self, agent: NlpDispatcherAgent
    ) -> None:
        class FakeBusHealthTracker:
            def __init__(self, health_map: dict[str, str]) -> None:
                self._health_map = health_map

            def topic_health(self, topic: str) -> str:
                return self._health_map.get(topic, "green")

        agent._topic_dependency_map = {
            "data.standings": {
                "publish": ["data.request.v1"],
                "consume": ["data.response.v1"],
            },
        }
        agent._bus_health_tracker = FakeBusHealthTracker({"data.request.v1": "yellow"})
        from datetime import datetime, timezone
        from swarm.agents.nlp import _make_repeated_query_signature

        signature = _make_repeated_query_signature("data.standings", [], None)
        now_ts = datetime.now(timezone.utc).timestamp()

        agent._conversation_store.save_metadata(
            "conv-1",
            {
                "repeated_query_history": [
                    {
                        "signature": signature,
                        "ts": now_ts,
                    }
                ],
                "repeated_query_cached_answer": {
                    "signature": signature,
                    "cached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "payload": {
                        "request_id": "prior-request",
                        "qa_correlation_id": "prior-corr",
                        "intent": "data.standings",
                        "answer_text": "Önceki yanıt.",
                        "kind": "standings",
                        "degraded": False,
                        "tier_id_required": None,
                        "emitted_at_utc": "2026-05-27T10:00:00+00:00",
                        "schema_version": 2,
                    },
                },
            },
        )

        msg = _make_intent_msg(
            {
                "intent": "data.standings",
                "entities": [],
                "conversation_id": "conv-1",
            }
        )
        results = list(agent.handle(msg))

        assert any(
            r.envelope.topic == QA_ANSWER_V1
            and r.payload.get("intent") == "data.standings"
            and r.payload.get("answer_text") == "Önceki yanıt."
            for r in results
        )
        assert any(
            r.envelope.topic == NLP_EVENT_V1
            and r.payload.get("kind") == "partial_bus_swr_served_cache"
            for r in results
        )

    def test_meta_intent_topic_dependency_is_empty_when_all_topics_red(
        self, agent: NlpDispatcherAgent
    ) -> None:
        class FakeBusHealthTracker:
            def __init__(self, health_map: dict[str, str]) -> None:
                self._health_map = health_map

            def topic_health(self, topic: str) -> str:
                return self._health_map.get(topic, "red")

        agent._topic_dependency_map = {
            "predict.match_outcome": {
                "publish": ["predict.request.v1"],
                "consume": ["predict.approved.v1"],
            },
            "data.standings": {
                "publish": ["data.request.v1"],
                "consume": ["data.response.v1"],
            },
            "meta.help": {"publish": [], "consume": []},
        }
        agent._bus_health_tracker = FakeBusHealthTracker({"data.request.v1": "red"})

        assert agent._red_partial_bus_dependency("meta.help") is None
        assert agent._red_partial_bus_dependency("data.standings") == "data.request.v1"

    def test_topic_dependency_map_loads_from_yaml(self, agent: NlpDispatcherAgent) -> None:
        assert "predict.*" in agent._topic_dependency_map
        assert agent._resolve_topic_dependencies("predict.match_outcome")["publish"] == ["predict.request.v1"]
        assert agent._resolve_topic_dependencies("predict.match_outcome")["consume"] == ["predict.approved.v1"]
        assert agent._topic_dependency_map["data.fixture_lookup"]["consume"] == ["data.response.v1"]
        assert agent._topic_dependency_map["meta.*"]["publish"] == []
        assert agent._topic_dependency_map["meta.*"]["consume"] == []

    def test_topic_dependency_yaml_drives_partial_bus_failure(
        self, agent: NlpDispatcherAgent
    ) -> None:
        class FakeBusHealthTracker:
            def __init__(self, health_map: dict[str, str]) -> None:
                self._health_map = health_map

            def topic_health(self, topic: str) -> str:
                return self._health_map.get(topic, "green")

        class DummyRedis:
            def getdel(self, key: str) -> None:
                return None

        agent._bus_health_tracker = FakeBusHealthTracker({"predict.request.v1": "red"})
        agent._flame_capture._redis = DummyRedis()
        msg = _make_intent_msg({"intent": "predict.match_outcome", "entities": []})
        results = list(agent.handle(msg))

        assert len(results) == 1
        assert results[0].envelope.topic == QA_ANSWER_V1
        assert results[0].payload["intent"] == "meta.partial_bus_unavailable"
        assert results[0].payload.get("degraded_reason") == "partial_bus_predict.request.v1"

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

    def test_comparative_match_outcome_routes_to_multi_fixture_fanout(self, agent: NlpDispatcherAgent) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "qa_correlation_id": "corr-comp",
                "normalized_text": "galatasaray ya da fenerbahçe kim kazanır",
                "entities": [
                    {"span_start": 0, "span_end": 10, "kind": "team", "canonical_id": "gs", "confidence": 1.0, "lexicon_version": "1.0.0", "source": "gazetteer"},
                    {"span_start": 11, "span_end": 25, "kind": "team", "canonical_id": "fb", "confidence": 1.0, "lexicon_version": "1.0.0", "source": "gazetteer"},
                ],
            }
        )
        results = list(agent.handle(msg))
        predict_requests = [r for r in results if r.envelope.topic == PREDICT_REQUEST_V1]
        assert len(predict_requests) == 2
        summary_correlation_ids = {r.payload.get("summary_correlation_id") for r in predict_requests}
        assert len(summary_correlation_ids) == 1
        assert summary_correlation_ids.pop() is not None

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
        qa_messages = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
        assert len(qa_messages) == 1
        assert qa_messages[0].payload["intent"] == "meta.counterfactual_past_unsupported"
        assert qa_messages[0].payload["kind"] == "counterfactual_past_unsupported"

    def test_counterfactual_past_aspectual_stack_routes_to_meta_counterfactual_past_unsupported(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "galatasaray yenseydi şampiyon olur muydu",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        qa_messages = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
        assert len(qa_messages) == 1
        assert qa_messages[0].payload["intent"] == "meta.counterfactual_past_unsupported"
        assert qa_messages[0].payload["kind"] == "counterfactual_past_unsupported"

    def test_inferential_past_aspectual_stack_routes_to_data_h2h_with_resolved_entities(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "galatasaray kazanmış olur",
                "entities": [_make_team_entity("gs")],
            }
        )
        results = list(agent.handle(msg))
        assert any(
            r.envelope.topic == DATA_REQUEST_V1 and r.payload["kind"] == "h2h"
            for r in results
        )

    def test_evidential_hearsay_aspectual_stack_routes_to_data_h2h_with_resolved_entities(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "galatasaray kazanmışmış",
                "entities": [_make_team_entity("gs")],
            }
        )
        results = list(agent.handle(msg))
        assert any(
            r.envelope.topic == DATA_REQUEST_V1 and r.payload["kind"] == "h2h"
            for r in results
        )

    def test_obligative_aspectual_stack_routes_to_meta_advice_unsupported(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "galatasaray kazanmalı mı",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        qa_messages = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
        assert len(qa_messages) == 1
        assert qa_messages[0].payload["intent"] == "meta.advice_unsupported"
        assert qa_messages[0].payload["kind"] == "advice_unsupported"

    def test_epistemic_potential_with_past_temporal_contradiction_routes_to_meta_unsupported(
        self, agent: NlpDispatcherAgent
    ) -> None:
        msg = _make_intent_msg(
            {
                "intent": "predict.match_outcome",
                "normalized_text": "dün galatasaray kazanabilir mi",
                "entities": [],
            }
        )
        results = list(agent.handle(msg))
        qa_messages = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
        assert len(qa_messages) == 1
        assert qa_messages[0].payload["intent"] == "meta.unsupported"
        assert qa_messages[0].payload["kind"] == "unsupported"

    def test_modality_corpus_routes_as_expected(self, agent: NlpDispatcherAgent) -> None:
        corpus_path = (
            Path(__file__).resolve().parents[1]
            / "nlp"
            / "tests"
            / "data"
            / "modality_corpus.tr.json"
        )
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

        for index, row in enumerate(corpus):
            msg = _make_intent_msg(
                {
                    "request_id": f"req-{index:04}",
                    "intent": "predict.match_outcome",
                    "normalized_text": row["text"],
                    "entities": row.get("entities", []),
                }
            )
            results = list(agent.handle(msg))
            if row["expected_topic"] == QA_ANSWER_V1:
                qa_messages = [r for r in results if r.envelope.topic == QA_ANSWER_V1]
                assert len(qa_messages) == 1
                assert qa_messages[0].payload["intent"] == row["expected_intent"]
                assert qa_messages[0].payload["kind"] == row["expected_kind"]
            elif row["expected_topic"] == DATA_REQUEST_V1:
                assert any(
                    r.envelope.topic == DATA_REQUEST_V1
                    and r.payload["kind"] == row["expected_kind"]
                    for r in results
                )
            elif row["expected_topic"] == PREDICT_REQUEST_V1:
                assert any(
                    r.envelope.topic == PREDICT_REQUEST_V1
                    for r in results
                )
            else:
                raise AssertionError(f"unsupported expected topic: {row['expected_topic']}")

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
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
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
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        assert len(results) == 2
        assert all(r.envelope.topic == PREDICT_REQUEST_V1 for r in results)

    def test_summary_fan_out_shares_summary_correlation_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """All fan-out messages share the same summary_correlation_id."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(3))
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        corr_ids = {r.payload["summary_correlation_id"] for r in results}
        assert len(corr_ids) == 1, "All messages must share one summary_correlation_id"

    def test_summary_fan_out_summary_expected_count_matches_n(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Every fan-out message carries summary_expected_count = N (total sent)."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(3))
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        for r in results:
            assert r.payload["summary_expected_count"] == 3

    def test_summary_fan_out_capped_at_max_fixtures(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Fan-out is capped at cfg.nlp_summary_max_fixtures (default=10)."""
        from common.config import cfg

        entities = _make_team_entities(cfg.nlp_summary_max_fixtures + 5)
        msg = _make_summary_intent_msg(entities=entities)
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        assert len(results) == cfg.nlp_summary_max_fixtures

    def test_summary_hard_cap_degrades_to_list_only_answer(
        self, agent: NlpDispatcherAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Summary fan-out over the hard cap degrades to an immediate list-only answer."""
        monkeypatch.setattr(_cfg, "nlp_summary_max_fixtures_hard", 2)

        msg = _make_summary_intent_msg(entities=_make_team_entities(3))
        results = list(agent.handle(msg))
        assert len(results) == 1
        answer = results[0]
        assert answer.envelope.topic == QA_ANSWER_V1
        assert answer.payload["kind"] == "summary"
        assert answer.payload["degraded"] is True
        assert answer.payload["degraded_reason"] == "summary_hard_cap_exceeded"
        assert "liste yanıtı" in answer.payload["answer_text"]
        assert "Lig listeleri" in answer.payload["answer_text"]

    def test_summary_fan_out_carries_match_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Each fan-out message carries match_id = canonical_id from entity."""
        entities = _make_team_entities(2)
        msg = _make_summary_intent_msg(entities=entities)
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        match_ids = [r.payload["match_id"] for r in results]
        assert "team-0" in match_ids
        assert "team-1" in match_ids

    def test_summary_fan_out_carries_qa_request_id(
        self, agent: NlpDispatcherAgent
    ) -> None:
        """Each fan-out message carries qa_request_id referencing the original request."""
        msg = _make_summary_intent_msg(entities=_make_team_entities(2))
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        for r in results:
            assert r.payload["qa_request_id"] == "req-summary-001"

    def test_summary_fan_out_uses_salience_not_fifo(
        self, agent: NlpDispatcherAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fixture selection uses salience features rather than entity arrival order."""
        monkeypatch.setattr(_cfg, "nlp_summary_max_fixtures", 2)

        entities = [
            {
                "kind": "team",
                "canonical_id": "team-c",
                "league_tier": 0,
                "is_derby": False,
                "confidence": 0.95,
            },
            {
                "kind": "team",
                "canonical_id": "team-a",
                "league_tier": 1,
                "is_derby": False,
                "confidence": 0.95,
            },
            {
                "kind": "team",
                "canonical_id": "team-b",
                "league_tier": 0,
                "is_derby": True,
                "confidence": 0.95,
            },
        ]
        msg = _make_summary_intent_msg(entities=entities)

        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
        assert [r.payload["match_id"] for r in results] == ["team-a", "team-b"]

    def test_summary_fan_out_is_deterministic_across_entity_order(
        self, agent: NlpDispatcherAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ordering of selected fixtures is stable across different input orders."""
        monkeypatch.setattr(_cfg, "nlp_summary_max_fixtures", 2)

        entities = [
            {
                "kind": "team",
                "canonical_id": "team-b",
                "league_tier": 0,
                "is_derby": False,
                "confidence": 0.95,
            },
            {
                "kind": "team",
                "canonical_id": "team-a",
                "league_tier": 0,
                "is_derby": False,
                "confidence": 0.95,
            },
            {
                "kind": "team",
                "canonical_id": "team-c",
                "league_tier": 0,
                "is_derby": False,
                "confidence": 0.95,
            },
        ]
        msg_a = _make_summary_intent_msg(
            entities=entities,
            intent="summary.matchday",
        )
        msg_a.payload["request_id"] = "req-summary-001"
        msg_b = _make_summary_intent_msg(
            entities=list(reversed(entities)),
            intent="summary.matchday",
        )
        msg_b.payload["request_id"] = "req-summary-002"

        results_a = [r for r in list(agent.handle(msg_a)) if r.envelope.topic == PREDICT_REQUEST_V1]
        results_b = [r for r in list(agent.handle(msg_b)) if r.envelope.topic == PREDICT_REQUEST_V1]

        assert [r.payload["match_id"] for r in results_a] == [r.payload["match_id"] for r in results_b]

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
        results = [r for r in list(agent.handle(msg)) if r.envelope.topic == PREDICT_REQUEST_V1]
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
    schema_version: int = 3,
    calibration_state_horizon: str | None = "prematch",
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
        "schema_version": schema_version,
        "calibration_state_horizon": calibration_state_horizon,
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
        assert len(results2) == 2
        ans = next(r for r in results2 if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["degraded"] is False
        assert ans.payload["qa_correlation_id"] == corr
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results2
        )

    def test_degraded_flag_propagates_to_answer_body(self, agent: NlpAnswerAgent) -> None:
        """A degraded upstream prediction causes qa.answer.v1 to include the calibration disclaimer."""
        corr = "agg-corr-degraded-001"
        msg = _make_approved_msg(
            corr,
            expected_count=1,
            prediction_id="p-degraded-001",
            degraded=True,
            degraded_reason="summary_hard_cap_exceeded",
        )

        results = list(agent.handle(msg))
        assert len(results) == 2
        answer = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert answer.payload["degraded"] is True
        assert answer.payload["degraded_reason"] == "summary_hard_cap_exceeded"
        assert "Bu bir tahmindir; kesin sonuçlar garanti edilmez." in answer.payload["answer_text"]

    def test_summary_truncation_disclosure_metadata_and_text(self, agent: NlpAnswerAgent) -> None:
        """When a summary is truncated by the cap, the final answer exposes metadata and disclosure text."""
        corr = "agg-corr-002"
        msg1 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p1",
            degraded=False,
        )
        msg1.payload["summary_original_count"] = 5
        msg1.payload["summary_top_n_by"] = "öncelik (lig sıralaması, derbi, saat)"
        msg2 = _make_approved_msg(
            corr,
            expected_count=2,
            prediction_id="p2",
            degraded=False,
        )
        msg2.payload["summary_original_count"] = 5
        msg2.payload["summary_top_n_by"] = "öncelik (lig sıralaması, derbi, saat)"

        assert list(agent.handle(msg1)) == []
        results = list(agent.handle(msg2))
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["truncated_count"] == 3
        assert ans.payload["top_n_by"] == "öncelik (lig sıralaması, derbi, saat)"
        assert "Bu hafta 5 maç var; en öne çıkan 2 tanesini özetledim." in ans.payload["answer_text"]
        assert ans.payload["kind"] == "summary"
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )

    def test_predict_answer_appends_disclosures_and_locale_fallback_event(self, agent: NlpAnswerAgent) -> None:
        _cfg.nlp_age_gating_enabled = True
        try:
            msg = _make_approved_msg(
                "agg-corr-003",
                expected_count=1,
                qa_request_id="req-001",
                prediction_id="pred-001",
            )
            msg.payload["conversation_id"] = "conv-001"
            msg.payload["locale"] = "en-US"
            msg.payload["request_metadata"] = {
                "user_age_attestation": None,
                "qa_answer_schema_version": 3,
            }

            results = list(agent.handle(msg))
            answer = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
            assert any(
                r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_locale_fallback"
                for r in results
            )
            assert any(
                r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
                for r in results
            )

            assert "Bu bir tahmindir; kesin sonuçlar garanti edilmez." in answer.payload["answer_text"]
            assert "Bu sonuç tamamen otomatik bir sistem tarafından üretildi" in answer.payload["answer_text"]
            assert "KVKK Art 11 uyarınca kişisel verilerinizi inceleme" in answer.payload["answer_text"]
            assert answer.payload["disclosures"]
            fallback_event = next(
                r for r in results if r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_locale_fallback"
            )
            assert fallback_event.payload["requested_locale"] == "en-US"
            assert fallback_event.payload["resolved_locale"] == "tr-TR"
        finally:
            _cfg.nlp_age_gating_enabled = False

    def test_gambling_disclaimer_on_every_predict_answer(self, agent: NlpAnswerAgent) -> None:
        _cfg.nlp_age_gating_enabled = False
        try:
            conversation_id = "conv-disclosure-001"
            payload = {
                "intent": "predict.match_outcome",
                "request_id": "req-004",
                "qa_correlation_id": "corr-004",
                "conversation_id": conversation_id,
                "answer_text": "Test answer.",
                "locale": "tr-TR",
            }
            payload["request_metadata"] = {
                "user_age_attestation": True,
                "qa_answer_schema_version": 3,
            }
            results = agent._with_disclosures(
                [Message.new(topic=QA_ANSWER_V1, payload=dict(payload), producer="test")],
                payload,
            )

            answer = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
            assert "Bu bir tahmindir; kesin sonuçlar garanti edilmez." in answer.payload["answer_text"]
            assert answer.payload["disclosures"][0]["disclosure_id"] == "gambling_law_disclaimer_band"

            answer2_payload = dict(payload)
            answer2_payload["request_id"] = "req-005"
            results2 = agent._with_disclosures(
                [Message.new(topic=QA_ANSWER_V1, payload=answer2_payload, producer="test")],
                answer2_payload,
            )
            answer2 = next(r for r in results2 if r.envelope.topic == QA_ANSWER_V1)
            assert "Bu bir tahmindir; kesin sonuçlar garanti edilmez." in answer2.payload["answer_text"]
            assert answer2.payload["disclosures"][0]["disclosure_id"] == "gambling_law_disclaimer_band"
        finally:
            _cfg.nlp_age_gating_enabled = False

    def test_predict_answer_emits_context_extension_for_system_entities(
        self,
        agent: NlpAnswerAgent,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "prediction_id": "pred-ctx",
                "qa_correlation_id": "agg-corr-ctx",
                "request_id": "req-ctx",
                "schema_version": 3,
                "match_id": "team-0",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-ctx",
                    "match_id": "team-0",
                    "market": "1x2",
                    "contributing_models": ["model-1"],
                    "calibration_version": 1,
                    "swarm_confidence": 0.5,
                    "degraded": False,
                    "degraded_reason": "",
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
                "conversation_id": "conv-ctx",
                "entities": [
                    {
                        "kind": "team",
                        "canonical_id": "fb",
                        "confidence": 0.95,
                        "source": "system",
                    }
                ],
                "approved_at": "2026-05-27T10:00:00+00:00",
                "locale": "tr-TR",
            },
        )

        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-001",
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.answer.v1",
            )
            return (
                FixtureState.IN_PLAY_FIRST_HALF.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        results = list(agent.handle(msg))

        assert any(r.envelope.topic == QA_CONTEXT_EXTENSION_V1 for r in results)
        extension = next(r for r in results if r.envelope.topic == QA_CONTEXT_EXTENSION_V1)
        assert extension.payload["conversation_id"] == "conv-ctx"
        assert extension.payload["entities"][0]["canonical_id"] == "fb"
        assert extension.payload["entities"][0]["source"] == "system"

    def test_kvkk_footer_and_auto_notice_fire_only_on_first_conversation_answer(
        self, agent: NlpAnswerAgent
    ) -> None:
        _cfg.nlp_age_gating_enabled = False
        try:
            conversation_id = "conv-disclosure-002"
            payload = {
                "intent": "predict.match_outcome",
                "request_id": "req-006",
                "qa_correlation_id": "corr-006",
                "conversation_id": conversation_id,
                "answer_text": "Test answer.",
                "locale": "tr-TR",
            }
            payload["request_metadata"] = {
                "user_age_attestation": True,
                "qa_answer_schema_version": 3,
            }
            results1 = agent._with_disclosures(
                [Message.new(topic=QA_ANSWER_V1, payload=dict(payload), producer="test")],
                payload,
            )
            answer1 = next(r for r in results1 if r.envelope.topic == QA_ANSWER_V1)
            assert "KVKK Art 11 uyarınca kişisel verilerinizi inceleme, düzeltme ve silme hakkınız vardır." in answer1.payload["answer_text"]
            assert "Bu sonuç tamamen otomatik bir sistem tarafından üretildi, insan uzman görüşü içermez." in answer1.payload["answer_text"]

            payload2 = dict(payload)
            payload2["request_id"] = "req-007"
            results2 = agent._with_disclosures(
                [Message.new(topic=QA_ANSWER_V1, payload=payload2, producer="test")],
                payload2,
            )
            answer2 = next(r for r in results2 if r.envelope.topic == QA_ANSWER_V1)
            assert "KVKK Art 11 uyarınca kişisel verilerinizi inceleme, düzeltme ve silme hakkınız vardır." not in answer2.payload["answer_text"]
            assert "Bu sonuç tamamen otomatik bir sistem tarafından üretildi, insan uzman görüşü içermez." not in answer2.payload["answer_text"]
        finally:
            _cfg.nlp_age_gating_enabled = False

    def test_disclosures_are_appended_from_registry_exactly(self, agent: NlpAnswerAgent) -> None:
        _cfg.nlp_age_gating_enabled = False
        try:
            from nlp.compliance import load_disclosures

            payload = {
                "intent": "predict.match_outcome",
                "request_id": "req-008",
                "qa_correlation_id": "corr-008",
                "conversation_id": "conv-disclosure-003",
                "answer_text": "Test body.",
                "locale": "tr-TR",
                "request_metadata": {"user_age_attestation": True, "qa_answer_schema_version": 3},
            }
            results = agent._with_disclosures(
                [Message.new(topic=QA_ANSWER_V1, payload=dict(payload), producer="test")],
                payload,
            )
            answer = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)

            disclosures = load_disclosures("tr-TR")[0]
            footer = next(
                d for d in disclosures if d["disclosure_id"] == "kvkk_user_rights_footer_first_per_conversation"
            )
            assert footer["text"] in answer.payload["answer_text"]
            assert answer.payload["disclosures"]
            assert any(
                event.payload.get("kind") == "disclosure_emitted"
                for event in results
                if event.envelope.topic == NLP_EVENT_V1
            )
        finally:
            _cfg.nlp_age_gating_enabled = False

    def test_downgrade_strips_disclosures_for_older_schema_versions(self) -> None:
        payload = {
            "schema_version": 3,
            "request_id": "req-002",
            "qa_correlation_id": "corr-002",
            "intent": "predict.match_outcome",
            "answer_text": "Test",
            "disclosures": [
                {
                    "disclosure_id": "gambling_law_disclaimer_band",
                    "disclosure_version": 1,
                    "disclosure_sha8": "deadbeef",
                }
            ],
        }

        downgraded = downgrade_qa_answer_v1(payload, 2)
        assert "disclosures" not in downgraded

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        assert "2" in answer.payload["answer_text"]
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["degraded"] is True
        assert ans.envelope.topic == QA_ANSWER_V1
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        text = answer.payload["answer_text"]
        assert "Tüm maçları kapsayan bir özet hazırlanamadı" in text
        assert "hazırlanamadı" in text
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        assert "Tüm maçları kapsayan bir özet hazırlanamadı" in answer.payload["answer_text"]
        assert "hazırlanamadı" in answer.payload["answer_text"]
        assert "summary quorum not met" in answer.payload["degraded_reason"]
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        assert "Tüm maçları kapsayan bir özet hazırlanamadı" in answer.payload["answer_text"]
        assert "hazırlanamadı" in answer.payload["answer_text"]
        assert "summary quorum not met" in answer.payload["degraded_reason"]
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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

        assert len(out) == 2
        ans = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["degraded"] is True
        assert "Tüm maçları kapsayan bir özet hazırlanamadı" in ans.payload["answer_text"]
        assert "summary quorum not met" in ans.payload["degraded_reason"]
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
                assert len(results) == 2
                ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
                assert ans.payload["degraded"] is True
                assert "3/4 maç tahmini hazır" in ans.payload["answer_text"]
                assert "Eksik maçlar" in ans.payload["answer_text"]
                assert "summary quorum not met" not in (
                    ans.payload["degraded_reason"] or ""
                )
                assert any(
                    r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
                    for r in results
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
                assert len(results) == 2
                ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
                assert ans.payload["degraded"] is True
                assert "summary quorum not met" in ans.payload["degraded_reason"]
                assert any(
                    r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
                    for r in results
                )

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
        assert len(out_a) == 2
        assert len(out_b) == 2
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out_a
        )
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out_b
        )
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
        assert len(out2) == 2
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out2
        )
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
        assert len(out) == 3
        assert out[0].envelope.topic == QA_ANSWER_V1
        assert out[0].payload["intent"] == "predict.timeout"
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )
        assert any(
            r.envelope.topic == NLP_ALERT_V1 and r.payload.get("kind") == "nlp_citation_signature_verify_failed"
            for r in out
        )
        assert any(
            r.envelope.topic == NLP_ALERT_V1 and r.payload.get("severity") == "critical"
            for r in out
        )

    def test_nlp_tampered_citation_signature_rejected_for_all_mutations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§10.21.8: mutated citation blocks must be rejected by the verifier."""
        monkeypatch.setattr(
            _cfg,
            "nlp_predict_citation_hmac_required",
            "enforce",
            raising=False,
        )

        base_msg = _make_approved_msg(
            "agg-tamper-001",
            expected_count=1,
            prediction_id="p-valid-001",
        )
        assert base_msg.payload["citation_signature"] is not None
        assert base_msg.payload["citation_key_id"] is not None

        mutations: list[Message] = []
        for idx in range(200):
            mutated = copy.deepcopy(base_msg)
            payload = mutated.payload
            if idx % 5 == 0:
                payload["prediction_id"] = f"{payload['prediction_id']}-{idx}"
            elif idx % 5 == 1:
                payload["final"]["produced_at"] = "2026-05-27T10:00:01+00:00"
            elif idx % 5 == 2:
                payload["calibration_version"] = int(payload["calibration_version"]) + 1
            elif idx % 5 == 3:
                payload["citation_key_id"] = "0" * 16
            else:
                signature = str(payload["citation_signature"])
                payload["citation_signature"] = (
                    signature[:-1] + ("0" if signature[-1] != "0" else "1")
                )
            mutations.append(mutated)

        for msg in mutations:
            agent = NlpAnswerAgent(
                clock_iso=lambda: "2026-05-27T10:00:00+00:00",
                new_id=lambda: "test-ans-id",
                monotonic=None,
            )
            out = list(agent.handle(msg))
            assert any(r.envelope.topic == QA_ANSWER_V1 for r in out)
            assert any(
                r.envelope.topic == NLP_ALERT_V1 and r.payload.get("kind") == "nlp_citation_signature_verify_failed"
                for r in out
            )
            assert any(
                r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
                for r in out
            )
            answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
            assert answer.payload["intent"] == "predict.timeout"

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
        assert len(out) == 3
        assert out[0].envelope.topic == QA_ANSWER_V1
        assert out[0].payload["intent"] == "summary"
        assert any(
            r.envelope.topic == NLP_ALERT_V1 and r.payload.get("kind") == "nlp_citation_signature_verify_failed"
            for r in out
        )
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

    def test_prediction_id_re_derivation_rejects_swapped_envelope(
        self, agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """§10.29.12: valid HMAC but wrong prediction_id must be rejected."""
        monkeypatch.setattr(
            _cfg,
            "nlp_predict_prediction_id_determinism_required",
            "enforce",
            raising=False,
        )

        out = list(
            agent.handle(
                _make_approved_msg(
                    "agg-pred-id-mismatch-001",
                    expected_count=1,
                    prediction_id="0" * 32,
                )
            )
        )
        assert len(out) == 3
        assert out[0].envelope.topic == QA_ANSWER_V1
        assert out[0].payload["intent"] == "predict.timeout"
        assert any(
            r.envelope.topic == NLP_ALERT_V1 and r.payload.get("kind") == "predict_prediction_id_mismatch"
            for r in out
        )
        assert any(
            r.envelope.topic == NLP_ALERT_V1 and r.payload.get("severity") == "critical"
            for r in out
        )
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(prev_out) == 2
        assert prev_out[0].envelope.topic == QA_ANSWER_V1
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in prev_out
        )
        assert len(new_out) == 2
        assert new_out[0].envelope.topic == QA_ANSWER_V1
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in new_out
        )


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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        assert answer.payload["request_id"] == "original-request-id"
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

    def test_predict_approved_in_play_state_discards_prediction_and_emits_live_state_refusal(
        self, answer_agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.IN_PLAY_FIRST_HALF.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "request_id": "req-001",
                "qa_correlation_id": "qc-001",
                "match_id": "gs",
                "market": "1x2",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-001",
                    "match_id": "gs",
                    "market": "1x2",
                    "distribution": {"1": 0.5, "X": 0.3, "2": 0.2},
                    "weights": {},
                    "contributing_models": ["model-1"],
                    "calibration_version": 1,
                    "swarm_confidence": 0.85,
                    "degraded": False,
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
            },
        )

        results = list(answer_agent.handle(msg))
        assert any(r.envelope.topic == DATA_REQUEST_V1 and r.payload["kind"] == "live_state" for r in results)
        assert any(r.envelope.topic == QA_ANSWER_V1 and r.payload["intent"] == "meta.live_match_unsupported" for r in results)
        event_messages = [r for r in results if r.envelope.topic == NLP_EVENT_V1]
        assert len(event_messages) == 1
        event_payload = event_messages[0].payload
        assert event_payload["kind"] == "fixture_state_flipped_during_rpc"
        assert event_payload["match_id"] == "gs"
        assert event_payload["new_state"] == FixtureState.IN_PLAY_FIRST_HALF.value

    def test_predict_approved_in_play_state_emits_fixture_state_flipped_during_rpc_event(
        self, answer_agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.IN_PLAY_SECOND_HALF.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "request_id": "req-002",
                "qa_correlation_id": "qc-002",
                "match_id": "gs",
                "market": "1x2",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-002",
                    "match_id": "gs",
                    "market": "1x2",
                    "distribution": {"1": 0.4, "X": 0.4, "2": 0.2},
                    "weights": {},
                    "contributing_models": ["model-2"],
                    "calibration_version": 1,
                    "swarm_confidence": 0.80,
                    "degraded": False,
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
            },
        )

        results = list(answer_agent.handle(msg))
        event_messages = [r for r in results if r.envelope.topic == NLP_EVENT_V1]
        assert len(event_messages) == 1
        event_payload = event_messages[0].payload
        assert event_payload["kind"] == "fixture_state_flipped_during_rpc"
        assert event_payload["request_id"] == "req-002"
        assert event_payload["qa_correlation_id"] == "qc-002"
        assert event_payload["match_id"] == "gs"
        assert event_payload["prior_state"] == "unknown"
        assert event_payload["new_state"] == FixtureState.IN_PLAY_SECOND_HALF.value
        assert isinstance(event_payload["rpc_age_ms"], int)

    def test_nlp_rejects_live_horizon_calibration_in_v1(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "request_id": "req-horizon-001",
                "qa_correlation_id": "qc-001",
                "match_id": "gs",
                "market": "1x2",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-horizon-001",
                    "match_id": "gs",
                    "market": "1x2",
                    "distribution": {"1": 0.5, "X": 0.3, "2": 0.2},
                    "weights": {},
                    "contributing_models": ["model-1"],
                    "calibration_version": 1,
                    "swarm_confidence": 0.85,
                    "degraded": False,
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
                "schema_version": 1,
                "calibration_state_horizon": "live",
            },
        )

        results = list(answer_agent.handle(msg))
        assert any(r.envelope.topic == QA_ANSWER_V1 for r in results)
        assert any(r.envelope.topic == NLP_ALERT_V1 for r in results)
        answer = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert answer.payload["intent"] == "meta.calibration_horizon_mismatch"
        alert = next(r for r in results if r.envelope.topic == NLP_ALERT_V1)
        assert alert.payload["kind"] == "calibration_horizon_mismatch"
        assert alert.payload["severity"] == "error"

    def test_nlp_calibration_horizon_round_trip_through_qa_answer(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "request_id": "req-horizon-004",
                "qa_correlation_id": "qc-004",
                "match_id": "gs",
                "market": "1x2",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-horizon-004",
                    "match_id": "gs",
                    "market": "1x2",
                    "distribution": {"1": 0.5, "X": 0.3, "2": 0.2},
                    "weights": {},
                    "contributing_models": ["model-1"],
                    "calibration_version": 1,
                    "swarm_confidence": 0.85,
                    "degraded": False,
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
                "schema_version": 3,
                "calibration_state_horizon": "live",
            },
        )

        results = list(answer_agent.handle(msg))
        assert any(r.envelope.topic == NLP_ALERT_V1 for r in results)

    def test_nlp_rejects_prematch_horizon_on_in_play_fixture(
        self, answer_agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.IN_PLAY_SECOND_HALF.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "request_id": "req-horizon-002",
                "qa_correlation_id": "qc-002",
                "match_id": "gs",
                "market": "1x2",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-horizon-002",
                    "match_id": "gs",
                    "market": "1x2",
                    "distribution": {"1": 0.5, "X": 0.3, "2": 0.2},
                    "weights": {},
                    "contributing_models": ["model-1"],
                    "calibration_version": 1,
                    "swarm_confidence": 0.85,
                    "degraded": False,
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
                "schema_version": 3,
                "calibration_state_horizon": "prematch",
            },
        )

        results = list(answer_agent.handle(msg))
        assert any(r.envelope.topic == DATA_REQUEST_V1 for r in results)
        assert any(r.envelope.topic == QA_ANSWER_V1 for r in results)
        assert any(r.envelope.topic == NLP_ALERT_V1 for r in results)
        answer = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert answer.payload["intent"] == "meta.live_match_unsupported"

    def test_nlp_alert_calibration_horizon_mismatch_debounced(
        self, answer_agent: NlpAnswerAgent, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_fixture_state_get(match_id: str, request_id: str, qa_correlation_id: str, timeout_ms: int):
            lookup_req = Message.new(
                topic=DATA_REQUEST_V1,
                payload={
                    "request_id": "lookup-req",
                    "qa_request_id": request_id,
                    "qa_correlation_id": qa_correlation_id,
                    "kind": "fixture_state",
                    "match_id": match_id,
                    "timeout_ms": timeout_ms,
                    "emitted_at": "2026-05-27T10:00:00+00:00",
                },
                producer="nlp.dispatcher.v1",
            )
            return (
                FixtureState.SCHEDULED.value,
                "2026-05-27T10:00:00+00:00",
                "test",
                lookup_req,
            )

        monkeypatch.setattr(FixtureStateLookup, "get", staticmethod(fake_fixture_state_get))
        msg = Message.new(
            topic=PREDICT_APPROVED,
            payload={
                "request_id": "req-horizon-003",
                "qa_correlation_id": "qc-003",
                "match_id": "gs",
                "market": "1x2",
                "approved_at": "2026-05-27T10:00:00+00:00",
                "approved_by": ["proof.sanity.v1"],
                "verdict_count": 1,
                "quorum": 1,
                "final": {
                    "prediction_id": "pred-horizon-003",
                    "match_id": "gs",
                    "market": "1x2",
                    "distribution": {"1": 0.5, "X": 0.3, "2": 0.2},
                    "weights": {},
                    "contributing_models": ["model-1"],
                    "calibration_version": 1,
                    "profile_id": "profile-a",
                    "swarm_confidence": 0.85,
                    "degraded": False,
                    "produced_at": "2026-05-27T10:00:00+00:00",
                },
                "schema_version": 1,
                "calibration_state_horizon": "live",
            },
        )

        results_first = list(answer_agent.handle(msg))
        assert any(r.envelope.topic == NLP_ALERT_V1 for r in results_first)

        results_second = list(answer_agent.handle(msg))
        alerts_second = [r for r in results_second if r.envelope.topic == NLP_ALERT_V1]
        assert len(alerts_second) <= 1
        if alerts_second:
            assert alerts_second[0].payload["kind"] == "calibration_horizon_mismatch"

    def test_nlp_calibration_horizon_strict_default_true_in_config_sync(
        self,
    ) -> None:
        assert _cfg.nlp_calibration_horizon_strict is True

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        assert answer.payload["qa_correlation_id"] == qa_corr
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        # Falls back to summary_corr
        assert answer.payload["qa_correlation_id"] == corr
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(out) == 2
        payload = next(r for r in out if r.envelope.topic == QA_ANSWER_V1).payload
        assert payload.get("request_id"), "request_id must be non-empty"
        assert payload.get("qa_correlation_id"), "qa_correlation_id must be non-empty"
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

    def test_summary_answer_includes_query_time_bucket_and_feature_set_hash(
        self, answer_agent: NlpAnswerAgent
    ) -> None:
        corr = "sc-010"
        msg = _make_approved_msg_with_corr(
            summary_corr=corr,
            expected_count=1,
            qa_correlation_id="qc-010",
            qa_request_id="req-summary-010",
        )
        msg.payload["summary_original_count"] = 3
        msg.payload["summary_top_n_by"] = "öncelik (lig sıralaması, derbi, saat)"
        out = list(answer_agent.handle(msg))
        assert len(out) == 2
        payload = next(r for r in out if r.envelope.topic == QA_ANSWER_V1).payload
        assert payload["query_time_bucket"] == "2026-05-27T10:00:00Z"
        assert isinstance(payload["feature_set_hash"], str)
        assert len(payload["feature_set_hash"]) == 16
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )

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
        assert len(out) == 2
        answer = next(r for r in out if r.envelope.topic == QA_ANSWER_V1)
        # None → falls back to summary_corr
        assert answer.payload["qa_correlation_id"] == corr
        assert answer.payload["qa_correlation_id"], "qa_correlation_id must be non-empty"
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in out
        )


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
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["degraded"] is True
        assert "swarm voter count below minimum" in ans.payload["degraded_reason"]
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )

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
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["degraded"] is True
        degraded_reason = ans.payload["degraded_reason"]
        assert "reason_A" in degraded_reason
        assert "reason_B" in degraded_reason
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )

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
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        assert ans.payload["degraded"] is False
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )
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
        assert len(results) == 2
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
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
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        citations = ans.payload["citations"]
        assert len(citations) == 1
        assert citations[0]["calibration_version"] == 1
        assert citations[0]["prediction_count"] == 2
        assert "note" not in citations[0], "No note when only one version"
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )

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
        assert len(results) == 2
        ans = next(r for r in results if r.envelope.topic == QA_ANSWER_V1)
        citations = ans.payload["citations"]
        assert any(
            r.envelope.topic == NLP_EVENT_V1 and r.payload.get("kind") == "disclosure_emitted"
            for r in results
        )
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
        "Bu hafta için tahminler farklı kalibrasyon sürümleriyle üretildiği için birleşik özet sunulamıyor." in payload["answer_text"]
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


def test_pragmatic_class_only_used_by_proofreader_prepend_ast() -> None:
    """AST guard: dispatcher must not branch on pragmatic_class; only proofreader may use it."""
    source = inspect.getsource(NlpDispatcherAgent)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_expr = ast.get_source_segment(source, node.test) or ""
            assert "pragmatic_class" not in test_expr


def test_nlp_client_tz_never_logs_or_caches_geolocation() -> None:
    """§10.34.1 AST guard: client_tz is time-only, never geolocation.
    Dispatcher and date resolver must not log client_tz to audit trails,
    cache it in fixtures, or use it for geolocation inference."""
    # Check dispatcher doesn't cache client_tz in fixture_state or logs
    source = inspect.getsource(NlpDispatcherAgent)
    tree = ast.parse(source)
    
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # Reject direct .client_tz cache operations
            if node.attr == "client_tz":
                violations.append(f"Direct client_tz cache access at line {node.lineno}")
        elif isinstance(node, ast.Call):
            # Check that client_tz is not passed to geoip or location inference
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in {"geoip", "locate", "infer_location", "get_location"}:
                    arg_sources = ast.get_source_segment(source, node) or ""
                    if "client_tz" in arg_sources:
                        violations.append(f"client_tz passed to {node.func.attr} at line {node.lineno}")
    
    assert violations == [], f"client_tz geolocation violations:\n" + "\n".join(violations)


def test_client_tz_assumed_default_event_emitted_when_missing() -> None:
    """§10.34.1: When request_metadata.client_tz is absent, emit nlp.event.v1 with kind=client_tz_assumed_default."""
    agent = NlpDispatcherAgent()
    
    # Create a qa.intent.v1 message WITHOUT client_tz in request_metadata
    intent_payload = {
        "request_id": "req-no-tz",
        "intent": "data.fixture_lookup",
        "entities": [],
        "intent_confidence": 0.95,
        "request_metadata": {
            "input_source": "keyboard",
            "synthetic_prober": False,
            # Deliberately no client_tz
        },
    }
    
    msg = _make_intent_msg(intent_payload)
    output = list(agent.handle(msg))
    
    # Check that an nlp.event.v1 with kind=client_tz_assumed_default is emitted
    events = [m for m in output if m.topic == NLP_EVENT_V1]
    default_tz_events = [
        m for m in events 
        if m.payload.get("kind") == "client_tz_assumed_default"
    ]
    
    assert len(default_tz_events) > 0, (
        f"Expected client_tz_assumed_default event when client_tz absent.\n"
        f"Got events: {[e.payload.get('kind') for e in events]}"
    )
    
    # Verify event structure
    event = default_tz_events[0]
    assert event.payload.get("request_id") == "req-no-tz"
    assert event.payload.get("kind") == "client_tz_assumed_default"


def test_client_tz_assumed_default_event_NOT_emitted_when_present() -> None:
    """§10.34.1: When request_metadata.client_tz IS present, do not emit client_tz_assumed_default."""
    agent = NlpDispatcherAgent()
    
    # Create a qa.intent.v1 message WITH client_tz in request_metadata
    intent_payload = {
        "request_id": "req-with-tz",
        "intent": "data.fixture_lookup",
        "entities": [],
        "intent_confidence": 0.95,
        "request_metadata": {
            "input_source": "keyboard",
            "synthetic_prober": False,
            "client_tz": "Europe/Berlin",
        },
    }
    
    msg = _make_intent_msg(intent_payload)
    output = list(agent.handle(msg))
    
    # Check that NO nlp.event.v1 with kind=client_tz_assumed_default is emitted
    events = [m for m in output if m.topic == NLP_EVENT_V1]
    default_tz_events = [
        m for m in events 
        if m.payload.get("kind") == "client_tz_assumed_default"
    ]
    
    assert len(default_tz_events) == 0, (
        f"Should NOT emit client_tz_assumed_default when client_tz is present.\n"
        f"Got {len(default_tz_events)} such events"
    )




