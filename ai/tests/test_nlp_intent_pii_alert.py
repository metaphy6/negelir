"""Tests for nlp.intent.v1 alerts on redacted TR PII in sanitized text."""
from __future__ import annotations

from swarm.agents.nlp import NlpIntentAgent
from swarm.agents.topics import NLP_ALERT_V1, NLP_EVENT_V1, QA_ANSWER_V1, QA_REQUEST_V1
from swarm.sdk.types import Message


def _make_qa_request_v1_msg() -> Message:
    return Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": "req-001",
            "locale": "tr-TR",
            "sanitized_text": "Merhaba [REDACTED:PHONE_TR:sha8=deadbeef] dünya",
            "sec_verdict": "pass",
            "emitted_at": "2026-05-27T10:00:00+00:00",
        },
        producer="sec.input.v1",
    )


def test_nlp_intent_agent_emits_alert_for_redacted_tr_pii() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg()))
    alert_messages = [m for m in out if m.envelope.topic == NLP_ALERT_V1]
    assert len(alert_messages) == 1
    alert = alert_messages[0].payload
    assert alert["kind"] == "nlp_pii_in_input_phone_tr"
    assert alert["request_id"] == "req-001"
    assert alert["subject"] == "deadbeef"


def test_nlp_intent_agent_attaches_shout_metadata_to_floor_response(monkeypatch) -> None:
    agent = NlpIntentAgent()
    monkeypatch.setattr(
        "swarm.agents.nlp.assert_minimum_signal",
        lambda text, cfg=None: ("meta.unsupported_fragment", None),
    )
    msg = Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": "req-002",
            "locale": "tr-TR",
            "sanitized_text": "GALATASARAY KAZANIR MI",
            "sec_verdict": "pass",
            "emitted_at": "2026-05-27T10:00:00+00:00",
        },
        producer="sec.input.v1",
    )
    out = list(agent.handle(msg))
    answer_messages = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    assert len(answer_messages) == 1
    assert answer_messages[0].payload["request_metadata"]["shout"] is True


def test_nlp_intent_agent_auto_detects_asr_input_and_debounces() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 0.0

        def monotonic(self) -> float:
            return self.now

        def advance(self, seconds: float) -> None:
            self.now += seconds

    clock = Clock()
    agent = NlpIntentAgent(monotonic=clock.monotonic)

    def make_asr_msg(request_id: str) -> Message:
        return Message.new(
            topic=QA_REQUEST_V1,
            payload={
                "request_id": request_id,
                "locale": "tr-TR",
                "sanitized_text": "eee yani galatasaray maçını tahmin et bu satır ASR gibi görünüyor",
                "sec_verdict": "pass",
                "emitted_at": "2026-05-27T10:00:00+00:00",
            },
            producer="sec.input.v1",
        )

    out1 = list(agent.handle(make_asr_msg("req-001")))
    events1 = [m for m in out1 if m.envelope.topic == NLP_EVENT_V1]
    assert len(events1) == 1
    assert events1[0].payload["kind"] == "asr_input_auto_detected"

    clock.advance(30.0)
    out2 = list(agent.handle(make_asr_msg("req-002")))
    events2 = [m for m in out2 if m.envelope.topic == NLP_EVENT_V1]
    assert len(events2) == 0

    clock.advance(31.0)
    out3 = list(agent.handle(make_asr_msg("req-003")))
    events3 = [m for m in out3 if m.envelope.topic == NLP_EVENT_V1]
    assert len(events3) == 1
    assert events3[0].payload["kind"] == "asr_input_auto_detected"
