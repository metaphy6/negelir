"""Phase 8 §8.9 DoD — planned-pause symmetry (§8.10 binding).

Proves:

1. tick() emits no scale_decision while the agent is paused.
2. tick() emits scale_throttled{reason=manual_pause} per signal target
   while paused and leader (mirrors the manual_pin_active path).
3. handle() in-flight ack emission still works during a pause.
4. TTL expiry inside tick() emits kind=maint_resumed (and no
   scale_throttled / scale_decision events in the same return).
5. Explicit ops.maint-resume short-circuits the TTL, clearing pause
   state before the deadline; subsequent tick() runs normally.
"""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.scaler import MaintScaler, NoopController
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message

_T0_NS = 1_000_000_000_000_000  # ~11.5 days from epoch, arbitrary fixed base

_SIGNALS = {
    "predictor.v1": {"queue_depth": 5.0, "in_flight": 2.0, "head_age_s": 0.1},
    "trainer.v1": {"queue_depth": 1.0, "in_flight": 0.0, "head_age_s": 0.0},
}


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m-sym-test",
        trace_id="t-sym-test",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _make_agent(t: list[int]) -> MaintScaler:
    leader = SingleProcessLeader(name="maint.scaler.v1")
    return MaintScaler(
        controller=NoopController(),
        leader=leader,
        clock_ns=lambda: t[0],
    )


# ── 1: halts publish path ─────────────────────────────────────────────

def test_pause_halts_scale_decisions() -> None:
    """tick() must not emit scale_decision while the agent is paused."""
    t = [_T0_NS]
    agent = _make_agent(t)
    # Pause directly (simulates having received a maint_pause event)
    agent._pause.paused = True
    agent._pause.deadline_ns = _T0_NS + 600_000_000_000  # 600 s from now

    msgs = agent.tick(_SIGNALS)
    kinds = {m.payload.get("kind") for m in msgs}
    assert "scale_decision" not in kinds


# ── 2: scale_throttled per target ────────────────────────────────────

def test_pause_emits_scale_throttled_per_target() -> None:
    """tick() emits exactly one scale_throttled{reason=manual_pause} per
    signal target while paused (mirrors manual_pin_active semantics)."""
    t = [_T0_NS]
    agent = _make_agent(t)
    agent._pause.paused = True
    agent._pause.deadline_ns = _T0_NS + 600_000_000_000

    msgs = agent.tick(_SIGNALS)
    throttled = [m for m in msgs if m.payload.get("kind") == "scale_throttled"]
    assert len(throttled) == len(_SIGNALS)
    for m in throttled:
        assert m.payload["reason"] == "manual_pause", m.payload
        assert "would_be" in m.payload
        assert m.envelope.topic == MAINT_EVENT


# ── 3: in-flight ack emission ────────────────────────────────────────

def test_ack_emission_works_during_pause() -> None:
    """handle() must still emit maint.ack.v1 while the publish path is
    paused (the ack path is not gated by PauseState.paused)."""
    t = [_T0_NS]
    agent = _make_agent(t)
    agent._pause.paused = True
    agent._pause.deadline_ns = _T0_NS + 600_000_000_000

    # Send a second maint_pause (a re-delivery or a resume call)
    msg = _wrap({
        "kind": "maint_pause",
        "request_id": "req-inflight-ack",
        "target": "maint.scaler.v1",
        "ttl_s": 600,
        "produced_at": "2024-01-01T00:00:00+00:00",
    })
    outs = list(agent.handle(msg))
    acks = [m for m in outs if m.envelope.topic == MAINT_ACK]
    assert acks, "in-flight ack emission must work while the publish path is paused"
    assert acks[0].payload["accepted"] is True


# ── 4: TTL expiry emits maint_resumed ────────────────────────────────

def test_ttl_expiry_emits_maint_resumed() -> None:
    """When the pause TTL has elapsed, tick() must emit maint_resumed and
    nothing else (scale decisions resume from the *next* tick call)."""
    t = [_T0_NS]
    agent = _make_agent(t)
    # Set pause whose deadline is already in the past relative to t[0]
    agent._pause.paused = True
    agent._pause.deadline_ns = _T0_NS - 1  # expired

    msgs = agent.tick(_SIGNALS)
    kinds = [m.payload.get("kind") for m in msgs]
    assert "maint_resumed" in kinds, kinds
    assert "scale_decision" not in kinds
    assert "scale_throttled" not in kinds
    # Verify the payload shape
    resumed_msgs = [m for m in msgs if m.payload.get("kind") == "maint_resumed"]
    assert len(resumed_msgs) == 1
    p = resumed_msgs[0].payload
    assert p.get("agent_id") == "maint.scaler.v1"
    assert p.get("kind_schema_version") == 1
    assert "produced_at" in p


# ── 5: explicit resume short-circuits TTL ───────────────────────────

def test_explicit_resume_short_circuits_ttl() -> None:
    """ops.maint-resume via handle() must clear the pause and deadline
    immediately, well before the TTL would have fired."""
    t = [_T0_NS]
    agent = _make_agent(t)

    # Pause with a long TTL
    pause_msg = _wrap({
        "kind": "maint_pause",
        "request_id": "req-pause-sc",
        "target": "maint.scaler.v1",
        "ttl_s": 600,
        "produced_at": "2024-01-01T00:00:00+00:00",
    })
    agent.handle(pause_msg)
    assert agent._pause.paused, "agent must be paused after maint_pause"

    # Resume explicitly (clock is still at T0, far from the deadline)
    resume_msg = _wrap({
        "kind": "maint_resume",
        "request_id": "req-resume-sc",
        "target": "maint.scaler.v1",
        "produced_at": "2024-01-01T00:00:00+00:00",
    })
    outs = list(agent.handle(resume_msg))

    # State cleared immediately
    assert not agent._pause.paused
    assert agent._pause.deadline_ns is None

    # Ack carries reason=resumed
    acks = [m for m in outs if m.envelope.topic == MAINT_ACK]
    assert acks, "resume must emit an ack"
    assert acks[0].payload.get("reason") == "resumed"

    # Subsequent tick must NOT emit maint_resumed (TTL path is inactive)
    msgs = agent.tick(_SIGNALS)
    kinds = [m.payload.get("kind") for m in msgs]
    assert "maint_resumed" not in kinds
