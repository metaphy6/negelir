"""Tests for the Phase 10 empty-input floor gate (§10.24.13)."""
from __future__ import annotations

from swarm.agents.nlp import NlpIntentAgent
from swarm.agents.topics import NLP_EVENT_V1, QA_ANSWER_V1, QA_REQUEST_V1
from swarm.sdk.types import Message


def _make_qa_request_v1_msg(text: str, request_id: str = "req-001") -> Message:
    return Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": request_id,
            "locale": "tr-TR",
            "sanitized_text": text,
            "sec_verdict": "pass",
            "emitted_at": "2026-06-03T12:00:00+00:00",
        },
        producer="sec.input.v1",
    )


def test_nlp_empty_input_returns_canned_help_no_pipeline() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert answer[0].payload["intent"] == "meta.help"
    assert answer[0].payload["kind"] == "meta.help"
    assert "Bana bir maç ya da takım sorabilirsin" in answer[0].payload["answer_text"]
    assert events[0].payload["kind"] == "empty_input_floor_response"


def test_nlp_whitespace_only_input_handled() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("   ", request_id="req-002")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]

    assert len(answer) == 1
    assert answer[0].payload["intent"] == "meta.help"
    assert answer[0].payload["kind"] == "meta.help"


def test_nlp_single_char_input_handled() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("a", request_id="req-003")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.unsupported_too_short"
    assert any(m.payload["intent"] == "meta.help" for m in out if m.envelope.topic == QA_ANSWER_V1)


def test_nlp_all_punctuation_input_handled() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("!!!???", request_id="req-004")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.unsupported_too_short"
    assert any(m.payload["intent"] == "meta.help" for m in out if m.envelope.topic == QA_ANSWER_V1)


def test_nlp_greeting_input_returns_help_with_safe_echo() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("selam", request_id="req-005")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert answer[0].payload["intent"] == "meta.help"
    assert "Selam!" in answer[0].payload["answer_text"]
    assert events[0].payload["kind"] == "greeting_input_floor_response"


def test_nlp_greetings_table_is_closed_set() -> None:
    from nlp.normalize import _load_greetings

    greetings = _load_greetings()
    assert greetings == {
        "merhaba",
        "selam",
        "selamün aleyküm",
        "slm",
        "meraba",
        "merhabalar",
    }
