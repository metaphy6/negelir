"""Phase 8 §8.6 — `maint.schema.v1` (Detector A) smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.types import Envelope, Message


def _wrap(topic: str, payload: dict) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=topic,  # type: ignore[arg-type]
        producer="x",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_subscribes_maint_event_publishes_event_and_ack() -> None:
    """Per Phase 8 §8.10, the schema sentinel subscribes MAINT_EVENT
    so it can react to operator-driven maint_pause / maint_resume.
    Sample taps for Detector A still flow through :meth:`observe`."""
    a = MaintSchemaSentinel()
    assert a.name == "maint.schema.v1"
    assert MAINT_EVENT in a.subscribes
    assert MAINT_EVENT in a.publishes
    assert MAINT_ACK in a.publishes


def test_observe_drops_messages_with_blank_topic() -> None:
    agent = MaintSchemaSentinel()
    out = list(agent.observe(_wrap("", {"foo": "bar"})))
    assert out == []


def test_observe_returns_empty_for_unknown_topic_when_validator_throws() -> None:
    """Sentinel must never crash the producer — validator errors are
    folded into a drift notification, not a raise."""
    agent = MaintSchemaSentinel()
    # `nonexistent.topic.v1` will fail kind/flat lookup; sentinel
    # treats that as an error and emits drift (subject to bucket).
    out = list(agent.observe(_wrap("nonexistent.topic.v1", {})))
    # Either empty (token bucket starved) or a drift notification —
    # never a raise.
    for m in out:
        assert m.payload.get("kind") == "schema_drift_detected"
