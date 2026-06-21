"""Envelope + Message basics."""
from __future__ import annotations

from swarm.sdk.types import ENVELOPE_SCHEMA_VERSION, Envelope, Message, Topic


def test_envelope_defaults_are_unique() -> None:
    a = Envelope()
    b = Envelope()
    assert a.message_id != b.message_id
    assert a.trace_id != b.trace_id
    assert a.schema_version == ENVELOPE_SCHEMA_VERSION
    assert a.attempt == 0


def test_envelope_roundtrip_dict() -> None:
    env = Envelope(topic=Topic("x.y"), producer="p1", attempt=2)
    restored = Envelope.from_dict(env.as_dict())
    assert restored == env


def test_envelope_from_dict_fills_defaults() -> None:
    env = Envelope.from_dict({"topic": "echo.in"})
    assert env.topic == "echo.in"
    assert env.message_id  # auto-filled
    assert env.trace_id
    assert env.schema_version == ENVELOPE_SCHEMA_VERSION


def test_envelope_attempt_coerces_to_int() -> None:
    env = Envelope.from_dict({"topic": "x", "attempt": "3"})
    assert env.attempt == 3


def test_message_new_carries_topic_and_trace() -> None:
    m = Message.new("echo.in", {"k": 1}, producer="p", trace_id="trace123")
    assert m.envelope.topic == "echo.in"
    assert m.envelope.trace_id == "trace123"
    assert m.envelope.producer == "p"
    assert m.payload == {"k": 1}


def test_message_with_envelope_replaces_envelope() -> None:
    m = Message.new("a", {"x": 1})
    new_env = Envelope(topic=Topic("a"), attempt=5)
    m2 = m.with_envelope(new_env)
    assert m2.envelope.attempt == 5
    assert m2.payload is m.payload  # not deep-copied
