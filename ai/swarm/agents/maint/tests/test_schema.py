"""Phase 8 §8.6 — `maint.schema.v1` (Detector A) smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.topics import MAINT_EVENT
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


def test_subscribes_empty_publishes_maint_event() -> None:
    a = MaintSchemaSentinel()
    assert a.name == "maint.schema.v1"
    assert a.subscribes == ()
    assert MAINT_EVENT in a.publishes


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
