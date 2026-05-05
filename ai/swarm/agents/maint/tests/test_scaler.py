"""Phase 8 §8.2 — `maint.scaler.v1` smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.scaler import MaintScaler, NoopController
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


def test_subscribes_publishes_set() -> None:
    a = MaintScaler()
    assert a.name == "maint.scaler.v1"
    assert MAINT_EVENT in a.subscribes
    assert MAINT_EVENT in a.publishes
    assert MAINT_ACK in a.publishes


def test_manual_scale_pin_emits_decision_and_ack() -> None:
    controller = NoopController()
    agent = MaintScaler(controller=controller, leader=SingleProcessLeader("maint.scaler.v1"))
    msg = _wrap({
        "kind": "manual_scale_pin",
        "request_id": "req-001",
        "client_id": "ops",
        "target": "predictor.elo",
        "replicas": 5,
        "ttl_s": 60,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "test",
    })
    out = list(agent.handle(msg))
    kinds = [m.payload.get("kind") for m in out]
    assert "scale_decision" in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)
    assert ("predictor.elo", 5) in controller.applied


def test_non_leader_no_decision_but_acks() -> None:
    leader = SingleProcessLeader("maint.scaler.v1")
    leader.shed()
    agent = MaintScaler(leader=leader)
    out = list(agent.handle(_wrap({
        "kind": "manual_scale_pin",
        "request_id": "req-002",
        "client_id": "ops",
        "target": "predictor.elo",
        "replicas": 3,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "scale_decision" not in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


def test_unrelated_kind_ignored() -> None:
    agent = MaintScaler()
    assert list(agent.handle(_wrap({"kind": "bogus"}))) == []


def test_maint_pause_acks_when_target_matches() -> None:
    agent = MaintScaler()
    msgs = list(agent.handle(_wrap({
        "kind": "maint_pause",
        "request_id": "req-003",
        "client_id": "ops",
        "target": "all",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "rolling",
    })))
    assert any(m.envelope.topic == MAINT_ACK for m in msgs)
