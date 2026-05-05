"""Phase 8 §8.5 — `maint.dlq.v1` smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.dlq import RECURSION_DENY_SET, MaintDlqSupervisor
from swarm.agents.maint.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_subscribes_publishes() -> None:
    a = MaintDlqSupervisor()
    assert a.name == "maint.dlq.v1"
    assert MAINT_EVENT in a.subscribes


def test_replay_emits_notification_and_ack() -> None:
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-001",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "max_msgs": 10,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


def test_recursion_deny_for_maint_event_dlq() -> None:
    """The supervisor must not loop on its own DLQ."""
    agent = MaintDlqSupervisor()
    target = next(iter(RECURSION_DENY_SET))
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-002",
        "client_id": "ops",
        "target": target,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" not in kinds
    # Must produce ack rejecting and a topic_disabled notification.
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload["accepted"] is False


def test_dedup_blocks_repeat_request() -> None:
    agent = MaintDlqSupervisor()
    msg = _wrap({
        "kind": "dlq_replay",
        "request_id": "req-003",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })
    list(agent.handle(msg))  # first call accepted
    out2 = list(agent.handle(msg))  # second call dedup-rejected
    acks = [m for m in out2 if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload["accepted"] is False


def test_non_leader_acks_skip() -> None:
    leader = SingleProcessLeader("maint.dlq.v1")
    leader.shed()
    agent = MaintDlqSupervisor(leader=leader)
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-004",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" not in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)
