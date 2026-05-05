"""Phase 8 §8.7 + §8.8 — `maint.sec.v1` smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.sec import (
    InMemoryDecimator,
    InMemoryPatternStore,
    MaintSecAgent,
)
from swarm.agents.maint.topics import MAINT_ACK, MAINT_EVENT
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
    a = MaintSecAgent()
    assert a.name == "maint.sec.v1"
    assert MAINT_EVENT in a.subscribes
    assert MAINT_ACK in a.publishes


def test_quarantine_clear_promotes_pattern() -> None:
    store = InMemoryPatternStore()
    agent = MaintSecAgent(pattern_store=store)
    out = list(agent.handle(_wrap({
        "kind": "quarantine_clear",
        "request_id": "req-001",
        "client_id": "ops",
        "target": "qid:abc123",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "false positive",
        "details": {"pattern": "/* SAFE_QUERY */"},
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "pattern_allowlist_pending" in kinds
    assert "pattern_allowlist_added" in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


def test_quarantine_clear_dedup() -> None:
    agent = MaintSecAgent()
    msg = _wrap({
        "kind": "quarantine_clear",
        "request_id": "req-002",
        "client_id": "ops",
        "target": "qid:abc",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "fp",
        "details": {"pattern": "p1"},
    })
    list(agent.handle(msg))
    out2 = list(agent.handle(msg))
    # On dedup we ack but emit no further notifications.
    kinds = [m.payload.get("kind") for m in out2 if m.envelope.topic == MAINT_EVENT]
    assert kinds == []


def test_quarantine_clear_no_pattern_acks_noop() -> None:
    agent = MaintSecAgent()
    out = list(agent.handle(_wrap({
        "kind": "quarantine_clear",
        "request_id": "req-003",
        "client_id": "ops",
        "target": "qid:x",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "fp",
    })))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload["accepted"] is True


def test_denylist_decimate_emits_summary() -> None:
    decimator = InMemoryDecimator(entries={f"k{i}": float(i) for i in range(50)})
    agent = MaintSecAgent(decimator=decimator)
    out = list(agent.handle(_wrap({
        "kind": "denylist_decimate_now",
        "request_id": "req-004",
        "client_id": "ops",
        "target": "all",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "manual",
    })))
    kinds = [m.payload.get("kind") for m in out if m.envelope.topic == MAINT_EVENT]
    assert "denylist_decimate" in kinds


def test_unrelated_kind_ignored() -> None:
    agent = MaintSecAgent()
    out = list(agent.handle(_wrap({"kind": "scale_decision"})))
    assert out == []
