"""Tests for nlp.intent.v1 alerts on redacted TR PII in sanitized text."""
from __future__ import annotations

from swarm.agents.nlp import NlpIntentAgent
from swarm.agents.topics import NLP_ALERT_V1, QA_REQUEST_V1
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
