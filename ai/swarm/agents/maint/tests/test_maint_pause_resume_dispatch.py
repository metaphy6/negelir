"""Phase 8 §8.10 + §8.13.5 — maint_pause/resume handlers across the
maintenance plane.

Covers:

* maint.schema.v1 + maint.sec.v1 now accept maint_pause / maint_resume
  (parity with maint.scaler.v1 / maint.dlq.v1, all four routed in
  ``_ack_routing._ACK_ROUTING_TABLE``).
* All four agents emit ``maint.ack.v1{accepted=True, reason=not_targeted}``
  when target is a single agent id that is not theirs — this is the
  contract that lets the ops console get a complete ack set on
  single-target pauses.
* Self-isolated agents refuse maint_pause with
  ``reason=requires_resume_first``.
* maint_resume after self-isolation succeeds with
  ``reason=resumed_from_isolation`` and clears the isolation flag.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.sec import MaintSecAgent
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
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


_ALL_PAUSE_AGENTS = (
    ("maint.scaler.v1", MaintScaler),
    ("maint.dlq.v1", MaintDlqSupervisor),
    ("maint.schema.v1", MaintSchemaSentinel),
    ("maint.sec.v1", MaintSecAgent),
)


def _ack_payload(out, *, expected_acceptor: str) -> dict:
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1, f"expected exactly one ack, got {len(acks)}"
    p = acks[0].payload
    assert p["accepted_by"] == expected_acceptor
    return p


# ── per-agent: pause('all') accepted ────────────────────────────────


@pytest.mark.parametrize("name,ctor", _ALL_PAUSE_AGENTS)
def test_pause_all_accepted(name, ctor) -> None:
    agent = ctor()
    out = list(agent.handle(_wrap({
        "kind": "maint_pause",
        "request_id": f"req-{name}-pause",
        "client_id": "ops",
        "target": "all",
        "ttl_s": 120,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    p = _ack_payload(out, expected_acceptor=name)
    assert p["accepted"] is True
    assert p["reason"] == "paused"


@pytest.mark.parametrize("name,ctor", _ALL_PAUSE_AGENTS)
def test_resume_all_after_pause(name, ctor) -> None:
    agent = ctor()
    list(agent.handle(_wrap({
        "kind": "maint_pause",
        "request_id": f"req-{name}-pause-2",
        "client_id": "ops",
        "target": "all",
        "ttl_s": 120,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    out = list(agent.handle(_wrap({
        "kind": "maint_resume",
        "request_id": f"req-{name}-resume",
        "client_id": "ops",
        "target": "all",
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    p = _ack_payload(out, expected_acceptor=name)
    assert p["accepted"] is True
    assert p["reason"] == "resumed"


# ── single-target dispatch: non-matching agents ack 'not_targeted' ─


@pytest.mark.parametrize("name,ctor", _ALL_PAUSE_AGENTS)
def test_pause_single_target_other_acks_not_targeted(name, ctor) -> None:
    agent = ctor()
    other = "maint.notthisone.v1"
    out = list(agent.handle(_wrap({
        "kind": "maint_pause",
        "request_id": f"req-nt-{name}",
        "client_id": "ops",
        "target": other,
        "ttl_s": 60,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    p = _ack_payload(out, expected_acceptor=name)
    assert p["accepted"] is True
    assert p["reason"] == "not_targeted"


@pytest.mark.parametrize("name,ctor", _ALL_PAUSE_AGENTS)
def test_resume_single_target_other_acks_not_targeted(name, ctor) -> None:
    agent = ctor()
    other = "maint.notthisone.v1"
    out = list(agent.handle(_wrap({
        "kind": "maint_resume",
        "request_id": f"req-nt-r-{name}",
        "client_id": "ops",
        "target": other,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    p = _ack_payload(out, expected_acceptor=name)
    assert p["accepted"] is True
    assert p["reason"] == "not_targeted"


# ── self-isolation refuses pause until operator resumes ────────────


@pytest.mark.parametrize("name,ctor", _ALL_PAUSE_AGENTS)
def test_self_isolated_refuses_pause(name, ctor) -> None:
    agent = ctor()
    agent._pause.self_isolated = True
    out = list(agent.handle(_wrap({
        "kind": "maint_pause",
        "request_id": f"req-iso-{name}",
        "client_id": "ops",
        "target": name,
        "ttl_s": 60,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    p = _ack_payload(out, expected_acceptor=name)
    assert p["accepted"] is False
    assert p["reason"] == "requires_resume_first"


@pytest.mark.parametrize("name,ctor", _ALL_PAUSE_AGENTS)
def test_resume_clears_self_isolation(name, ctor) -> None:
    agent = ctor()
    agent._pause.self_isolated = True
    out = list(agent.handle(_wrap({
        "kind": "maint_resume",
        "request_id": f"req-iso-r-{name}",
        "client_id": "ops",
        "target": name,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })))
    p = _ack_payload(out, expected_acceptor=name)
    assert p["accepted"] is True
    assert p["reason"] == "resumed_from_isolation"
    assert agent._pause.self_isolated is False


# ── routing-table contract: every consumer wired here is reachable ─


def test_routing_table_consumers_exist_in_test_matrix() -> None:
    """Guard: if someone widens the routing table for maint_pause /
    maint_resume, they must extend ``_ALL_PAUSE_AGENTS`` so the
    per-handler tests stay truthful."""
    from swarm.agents.maint._ack_routing import expected_ack_set
    declared = set(expected_ack_set("maint_pause"))
    covered = {n for n, _ in _ALL_PAUSE_AGENTS}
    assert declared == covered, (
        f"routing table declares {declared} but tests only cover {covered}"
    )
    declared_r = set(expected_ack_set("maint_resume"))
    assert declared_r == covered
