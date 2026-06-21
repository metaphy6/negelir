"""Phase 8 §8.13.5 — idempotency matrix: proof tests for bullet 1.

Covers every cell of the state x command matrix for the three
operator-driven state-change verbs: maint-pause, maint-resume,
dlq-resume (= dlq_unfreeze on the bus).

Matrix under test:
  running   + maint-pause    -> accept, "paused"
  running   + maint-resume   -> accept (no-op), "already_running"
  running   + dlq-resume     -> accept (no-op), "already_running"
  paused    + maint-pause    -> accept (no-op, TTL-widen), "already_paused"
  paused    + maint-resume   -> accept, "resumed"
  paused    + dlq-resume     -> accept (no-op), "paused_not_blocked"
  isolated  + maint-pause    -> reject, "requires_resume_first"
  isolated  + maint-resume   -> accept (clears isolation), "resumed_from_isolation"
  isolated  + dlq-resume     -> accept (no-op), "already_unfrozen"
  dlq-frozen + maint-pause   -> accept, "paused"  (topic still frozen)
  dlq-frozen + maint-resume  -> accept, "resumed" (topic still frozen)
  dlq-frozen + dlq-resume    -> accept, "unfrozen" (topic unfrozen)
  dlq-frozen (isolated) + dlq-resume -> accept, "unfrozen" (partial)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.maint._pause_state import PauseState
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.types import Envelope, Message


# ---- helpers ---------------------------------------------------------


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


def _pause_msg(request_id: str = "req-pause", target: str = "all",
               ttl_s: int = 300) -> Message:
    return _wrap({
        "kind": "maint_pause",
        "request_id": request_id,
        "client_id": "ops",
        "target": target,
        "ttl_s": ttl_s,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })


def _resume_msg(request_id: str = "req-resume", target: str = "all") -> Message:
    return _wrap({
        "kind": "maint_resume",
        "request_id": request_id,
        "client_id": "ops",
        "target": target,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })


def _unfreeze_msg(target_dlq: str, request_id: str = "req-unfreeze") -> Message:
    return _wrap({
        "kind": "dlq_unfreeze",
        "request_id": request_id,
        "client_id": "ops",
        "target": target_dlq,
        "produced_at": "2025-01-01T00:00:00+00:00",
    })


def _ack_reason(out: list) -> str:
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1, f"expected 1 ack, got {len(acks)}"
    return str(acks[0].payload["reason"])


def _ack_accepted(out: list) -> bool:
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1
    return bool(acks[0].payload["accepted"])


# ---- PauseState unit tests for every matrix cell --------------------


def test_pause_state_running_pause() -> None:
    """running + maint-pause -> accept, reason='paused'"""
    st = PauseState()
    res = st.apply_pause(ttl_s=300, now_ns=0)
    assert res.accepted is True
    assert res.reason == "paused"
    assert res.paused is True


def test_pause_state_running_resume_no_op() -> None:
    """running + maint-resume -> accept (no-op), reason='already_running'"""
    st = PauseState()
    res = st.apply_resume()
    assert res.accepted is True
    assert res.reason == "already_running"
    assert res.paused is False


def test_pause_state_paused_pause_idempotent() -> None:
    """paused + maint-pause -> accept (no-op), reason='already_paused'"""
    st = PauseState(paused=True, deadline_ns=9_000_000_000_000)
    res = st.apply_pause(ttl_s=10, now_ns=1_000_000_000)
    assert res.accepted is True
    assert res.reason == "already_paused"


def test_pause_state_paused_resume() -> None:
    """paused + maint-resume -> accept, reason='resumed'"""
    st = PauseState(paused=True, deadline_ns=1_000_000_000_000)
    res = st.apply_resume()
    assert res.accepted is True
    assert res.reason == "resumed"
    assert res.paused is False


def test_pause_state_isolated_pause_rejected() -> None:
    """self-isolated + maint-pause -> reject, reason='requires_resume_first'"""
    st = PauseState(self_isolated=True)
    res = st.apply_pause(ttl_s=300, now_ns=0)
    assert res.accepted is False
    assert res.reason == "requires_resume_first"
    assert res.paused is False


def test_pause_state_isolated_resume_clears() -> None:
    """self-isolated + maint-resume -> accept, reason='resumed_from_isolation'"""
    st = PauseState(self_isolated=True)
    res = st.apply_resume()
    assert res.accepted is True
    assert res.reason == "resumed_from_isolation"
    assert res.self_isolated is False


# ---- dlq_unfreeze integration tests (MaintDlqSupervisor) ------------


def test_dlq_resume_running_not_frozen_already_running() -> None:
    """8.13.5: running + dlq-resume (not frozen) -> already_running"""
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_unfreeze_msg("predict.vote.dlq")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "already_running"


def test_dlq_resume_paused_not_frozen_paused_not_blocked() -> None:
    """8.13.5: paused + dlq-resume (not frozen) -> paused_not_blocked"""
    agent = MaintDlqSupervisor()
    list(agent.handle(_pause_msg()))
    out = list(agent.handle(_unfreeze_msg("predict.vote.dlq", request_id="r2")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "paused_not_blocked"


def test_dlq_resume_isolated_not_frozen_already_unfrozen() -> None:
    """8.13.5: self-isolated + dlq-resume (not frozen) -> already_unfrozen (no-op)"""
    agent = MaintDlqSupervisor()
    agent._pause.self_isolated = True
    out = list(agent.handle(_unfreeze_msg("predict.vote.dlq")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "already_unfrozen"


def test_dlq_resume_frozen_running_unfreezes() -> None:
    """8.13.5: dlq-frozen + dlq-resume (running) -> unfrozen"""
    agent = MaintDlqSupervisor()
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    out = list(agent.handle(_unfreeze_msg("predict.vote.dlq")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "unfrozen"
    assert "predict.vote.dlq" not in agent._frozen_topics


def test_dlq_resume_frozen_paused_unfreezes_partial() -> None:
    """8.13.5: dlq-frozen + paused + dlq-resume -> unfrozen (partial:
    topic cleared but replays blocked until maint-resume)."""
    agent = MaintDlqSupervisor()
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    list(agent.handle(_pause_msg()))
    out = list(agent.handle(_unfreeze_msg("predict.vote.dlq", request_id="r2")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "unfrozen"
    assert "predict.vote.dlq" not in agent._frozen_topics
    # Agent still paused -- partial outcome.
    assert agent._pause.paused is True


def test_dlq_resume_frozen_isolated_unfreezes_partial() -> None:
    """8.13.5: self-isolated + dlq-frozen + dlq-resume -> unfrozen (partial)."""
    agent = MaintDlqSupervisor()
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    agent._pause.self_isolated = True
    out = list(agent.handle(_unfreeze_msg("predict.vote.dlq")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "unfrozen"
    assert "predict.vote.dlq" not in agent._frozen_topics
    # Isolation still set -- only maint-resume clears it.
    assert agent._pause.self_isolated is True


def test_dlq_frozen_maint_pause_topic_still_frozen() -> None:
    """8.13.5: dlq-frozen + maint-pause -> accept 'paused', topic still frozen."""
    agent = MaintDlqSupervisor()
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    out = list(agent.handle(_pause_msg()))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "paused"
    assert "predict.vote.dlq" in agent._frozen_topics


def test_dlq_frozen_maint_resume_frozen_preserved() -> None:
    """8.13.5: dlq-frozen + maint-resume -> accept 'resumed', frozen subset preserved."""
    agent = MaintDlqSupervisor()
    list(agent.handle(_pause_msg()))
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    out = list(agent.handle(_resume_msg()))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "resumed"
    # Topic freeze preserved -- maint-resume does NOT clear topic-level freezes.
    assert "predict.vote.dlq" in agent._frozen_topics


def test_full_idempotency_sequence() -> None:
    """Full 8.13.5 operator sequence:
    pause -> re-pause (no-op) -> resume -> resume (no-op)"""
    agent = MaintDlqSupervisor()
    out1 = list(agent.handle(_pause_msg("r1")))
    assert _ack_reason(out1) == "paused"
    out2 = list(agent.handle(_pause_msg("r2", ttl_s=60)))
    assert _ack_reason(out2) == "already_paused"
    assert _ack_accepted(out2) is True
    out3 = list(agent.handle(_resume_msg("r3")))
    assert _ack_reason(out3) == "resumed"
    out4 = list(agent.handle(_resume_msg("r4")))
    assert _ack_reason(out4) == "already_running"
    assert _ack_accepted(out4) is True


def test_isolation_pause_rejected_then_resume_clears() -> None:
    """8.13.5: self_isolate -> pause rejected -> resume clears -> pause succeeds."""
    agent = MaintDlqSupervisor()
    agent._pause.self_isolated = True
    out1 = list(agent.handle(_pause_msg()))
    assert _ack_accepted(out1) is False
    assert _ack_reason(out1) == "requires_resume_first"
    out2 = list(agent.handle(_resume_msg()))
    assert _ack_accepted(out2) is True
    assert _ack_reason(out2) == "resumed_from_isolation"
    assert agent._pause.self_isolated is False
    out3 = list(agent.handle(_pause_msg("r3")))
    assert _ack_reason(out3) == "paused"


# ---- §8.13.5 bullet 2: self-isolation precedence + sec.alert --------


def _sec_alerts(out: list) -> list:
    from swarm.agents.topics import SEC_ALERT
    return [m for m in out if m.envelope.topic == SEC_ALERT]


def test_isolated_pause_emits_maint_pause_rejected_alert() -> None:
    """8.13.5 bullet 2: self-isolated + maint-pause → sec.alert.v1
    kind=maint_pause_rejected, severity=warn, reason=self_isolated."""
    agent = MaintDlqSupervisor()
    agent._pause.self_isolated = True
    out = list(agent.handle(_pause_msg("req-iso-1")))
    alerts = _sec_alerts(out)
    assert len(alerts) == 1, f"expected 1 sec.alert, got {len(alerts)}"
    p = alerts[0].payload
    assert p["kind"] == "maint_pause_rejected"
    assert p["severity"] == "warn"
    assert p["reason"] == "self_isolated"


def test_isolated_pause_sec_alert_and_ack_both_present() -> None:
    """8.13.5 bullet 2: rejected pause yields both a rejection ack AND
    a sec.alert.v1 in the same output — operator gets both signals."""
    from swarm.agents.topics import MAINT_ACK, SEC_ALERT
    agent = MaintDlqSupervisor()
    agent._pause.self_isolated = True
    out = list(agent.handle(_pause_msg("req-iso-2")))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    assert len(acks) == 1 and not acks[0].payload["accepted"]
    assert len(alerts) == 1 and alerts[0].payload["kind"] == "maint_pause_rejected"


def test_running_pause_no_sec_alert() -> None:
    """8.13.5 bullet 2: a normal (non-isolated) maint-pause MUST NOT
    emit sec.alert.v1 — the alert fires only on self-isolation rejection."""
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_pause_msg("req-normal")))
    assert _ack_accepted(out) is True
    assert len(_sec_alerts(out)) == 0, "unexpected sec.alert on normal pause"


# ---- §8.13.5 bullet 3: TTL refresh semantics ------------------------


def test_ttl_refresh_larger_ttl_widens() -> None:
    """pause-while-paused with larger TTL → reason='ttl_refreshed', deadline extended,
    requested_ttl_s == effective_ttl_s == T2."""
    now_ns = 1_000_000_000                          # t = 1 s
    deadline_ns = now_ns + 300 * 1_000_000_000      # current deadline: 300 s from now
    st = PauseState(paused=True, deadline_ns=deadline_ns)
    res = st.apply_pause(ttl_s=600, now_ns=now_ns)
    assert res.accepted is True
    assert res.reason == "ttl_refreshed"
    assert res.deadline_ns == now_ns + 600 * 1_000_000_000, "deadline must be widened"
    assert res.requested_ttl_s == 600
    assert res.effective_ttl_s == 600


def test_ttl_refresh_smaller_ttl_no_op() -> None:
    """pause-while-paused with smaller TTL → reason='already_paused', deadline
    preserved, effective_ttl_s reflects the remaining (longer) TTL."""
    now_ns = 1_000_000_000
    deadline_ns = now_ns + 300 * 1_000_000_000
    st = PauseState(paused=True, deadline_ns=deadline_ns)
    res = st.apply_pause(ttl_s=60, now_ns=now_ns)
    assert res.accepted is True
    assert res.reason == "already_paused"
    assert res.deadline_ns == deadline_ns, "deadline must not be shortened"
    assert res.requested_ttl_s == 60
    assert res.effective_ttl_s == 300   # remaining TTL preserved


def test_ttl_refresh_equal_ttl_no_op() -> None:
    """pause-while-paused with exactly equal remaining TTL →
    reason='already_paused' (T2 == remaining → new_deadline == old_deadline → no-op)."""
    now_ns = 1_000_000_000
    deadline_ns = now_ns + 300 * 1_000_000_000
    st = PauseState(paused=True, deadline_ns=deadline_ns)
    res = st.apply_pause(ttl_s=300, now_ns=now_ns)
    assert res.accepted is True
    assert res.reason == "already_paused"
    assert res.deadline_ns == deadline_ns
    assert res.requested_ttl_s == 300
    assert res.effective_ttl_s == 300


def test_ttl_refresh_audit_details_via_agent() -> None:
    """Integration: MaintDlqSupervisor ack details carry requested_ttl_s and
    effective_ttl_s for both the 'ttl_refreshed' and 'already_paused' cases."""
    now_s = 0.0
    agent = MaintDlqSupervisor(clock_s=lambda: now_s)
    # First pause: 300 s
    list(agent.handle(_pause_msg("r1", ttl_s=300)))

    # Re-pause with 600 s (larger) → ttl_refreshed; both audit fields == 600
    out = list(agent.handle(_pause_msg("r2", ttl_s=600)))
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1
    ack_payload = acks[0].payload
    assert ack_payload["reason"] == "ttl_refreshed"
    assert ack_payload["details"]["requested_ttl_s"] == 600
    assert ack_payload["details"]["effective_ttl_s"] == 600

    # Re-pause with 60 s (smaller) → already_paused; effective stays at remaining (~600 s)
    out2 = list(agent.handle(_pause_msg("r3", ttl_s=60)))
    acks2 = [m for m in out2 if m.envelope.topic == MAINT_ACK]
    assert len(acks2) == 1
    ack2 = acks2[0].payload
    assert ack2["reason"] == "already_paused"
    assert ack2["details"]["requested_ttl_s"] == 60
    # effective_ttl_s must be >= 60 (the longer existing deadline is preserved)
    assert ack2["details"]["effective_ttl_s"] >= 60


# ---- §8.13.5 bullet 4: proof tests (a)(b)(c) action field + (d) full seq ----


def _maint_paused_events(out: list) -> list:
    return [
        m for m in out
        if m.envelope.topic == MAINT_EVENT and m.payload.get("kind") == "maint_paused"
    ]


def _maint_resumed_events(out: list) -> list:
    return [
        m for m in out
        if m.envelope.topic == MAINT_EVENT and m.payload.get("kind") == "maint_resumed"
    ]


def test_proof_a_second_pause_maint_paused_action_ttl_refresh() -> None:
    """8.13.5 bullet 4 (a): second pause while paused with larger TTL emits
    kind=maint_paused, action=ttl_refresh."""
    now_s = 0.0
    agent = MaintDlqSupervisor(clock_s=lambda: now_s)
    list(agent.handle(_pause_msg("r1", ttl_s=600)))
    out = list(agent.handle(_pause_msg("r2", ttl_s=1200)))
    assert _ack_reason(out) == "ttl_refreshed"
    events = _maint_paused_events(out)
    assert len(events) == 1, f"expected 1 maint_paused event, got {len(events)}"
    assert events[0].payload.get("action") == "ttl_refresh"


def test_proof_a_second_pause_maint_paused_action_no_op() -> None:
    """8.13.5 bullet 4 (a): second pause while paused with smaller TTL emits
    kind=maint_paused, action=no_op."""
    now_s = 0.0
    agent = MaintDlqSupervisor(clock_s=lambda: now_s)
    list(agent.handle(_pause_msg("r1", ttl_s=600)))
    out = list(agent.handle(_pause_msg("r2", ttl_s=300)))
    assert _ack_reason(out) == "already_paused"
    events = _maint_paused_events(out)
    assert len(events) == 1, f"expected 1 maint_paused event, got {len(events)}"
    assert events[0].payload.get("action") == "no_op"


def test_proof_a_first_pause_maint_paused_no_action() -> None:
    """8.13.5 bullet 4 (a): first pause emits kind=maint_paused without action field."""
    now_s = 0.0
    agent = MaintDlqSupervisor(clock_s=lambda: now_s)
    out = list(agent.handle(_pause_msg("r1", ttl_s=300)))
    assert _ack_reason(out) == "paused"
    events = _maint_paused_events(out)
    assert len(events) == 1
    assert "action" not in events[0].payload


def test_proof_b_resume_while_running_already_running() -> None:
    """8.13.5 bullet 4 (b): resume-while-running → ack already_running, accepted=True."""
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_resume_msg("r-resume-running")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "already_running"


def test_proof_c_isolated_pause_rejected_exit7() -> None:
    """8.13.5 bullet 4 (c): pause against self-isolated → rejected (accepted=False,
    reason=requires_resume_first) + sec.alert kind=maint_pause_rejected
    + opsctl publish_event returns exit code 7."""
    from swarm.agents.topics import SEC_ALERT
    agent = MaintDlqSupervisor()
    agent._pause.self_isolated = True
    out = list(agent.handle(_pause_msg("r-iso-c")))
    assert _ack_accepted(out) is False
    assert _ack_reason(out) == "requires_resume_first"
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    assert len(alerts) == 1
    assert alerts[0].payload["kind"] == "maint_pause_rejected"

    # Verify opsctl publish_event surfaces exit code 7 when it
    # receives a requires_resume_first rejection ack.
    from swarm.sdk.bus import InMemoryBus
    from xops.opsctl._exit_codes import ExitCode
    from xops.opsctl._publish import MAINT_ACK_TOPIC, build_envelope, publish_event

    bus = InMemoryBus()
    msg = build_envelope(kind="maint_pause", target="all", client_id="opsctl-test")
    request_id = msg.payload["request_id"]

    # Pre-stage acks: one rejection from maint.dlq.v1 + three acceptances
    # so publish_event exits immediately without waiting for the full timeout.
    bus.publish(Message(
        envelope=Envelope(topic=MAINT_ACK_TOPIC, producer="maint.dlq.v1"),
        payload={
            "request_id": request_id,
            "accepted": False,
            "accepted_by": "maint.dlq.v1",
            "reason": "requires_resume_first",
            "processed_at": "2025-01-01T00:00:00+00:00",
            "attempt": 0,
        },
    ))
    for accepted_by in ("maint.scaler.v1", "maint.schema.v1", "maint.sec.v1"):
        bus.publish(Message(
            envelope=Envelope(topic=MAINT_ACK_TOPIC, producer=accepted_by),
            payload={
                "request_id": request_id,
                "accepted": True,
                "accepted_by": accepted_by,
                "processed_at": "2025-01-01T00:00:00+00:00",
                "attempt": 0,
            },
        ))

    result = publish_event(bus, msg)
    assert result.exit_code == ExitCode.REQUIRES_RESUME_FIRST, (
        f"expected exit 7 (REQUIRES_RESUME_FIRST), got {result.exit_code}: {result.note}"
    )


def test_proof_d_full_sequence_self_isolate_pause_resume_ttl_expiry() -> None:
    """8.13.5 bullet 4 (d): full sequence
    self_isolate → pause rejected → resume → pause(T=600) → pause(T=300) no-op
    → pause(T=1200) refresh → wait expiry → kind=maint_resumed."""
    now_s = 0.0
    agent = MaintDlqSupervisor(clock_s=lambda: now_s)

    # Step 1 — self_isolate.
    agent._pause.self_isolated = True

    # Step 2 — pause rejected (self-isolated).
    out = list(agent.handle(_pause_msg("r-iso")))
    assert _ack_accepted(out) is False
    assert _ack_reason(out) == "requires_resume_first"

    # Step 3 — resume clears isolation.
    out = list(agent.handle(_resume_msg("r-res1")))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "resumed_from_isolation"
    assert not agent._pause.self_isolated

    # Step 4 — pause(T=600): fresh pause accepted.
    out = list(agent.handle(_pause_msg("r-p600", ttl_s=600)))
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "paused"
    # maint_paused event emitted without action field (first pause).
    p_events = _maint_paused_events(out)
    assert len(p_events) == 1
    assert "action" not in p_events[0].payload

    # Step 5 — pause(T=300): no-op (smaller TTL).
    out = list(agent.handle(_pause_msg("r-p300", ttl_s=300)))
    assert _ack_reason(out) == "already_paused"
    p_events = _maint_paused_events(out)
    assert len(p_events) == 1
    assert p_events[0].payload.get("action") == "no_op"

    # Step 6 — pause(T=1200): TTL refresh (larger than remaining 600 s).
    out = list(agent.handle(_pause_msg("r-p1200", ttl_s=1200)))
    assert _ack_reason(out) == "ttl_refreshed"
    p_events = _maint_paused_events(out)
    assert len(p_events) == 1
    assert p_events[0].payload.get("action") == "ttl_refresh"
    # Deadline is now 1200 s from t=0.

    # Step 7 — advance clock past the TTL (1200 s + 1 s).
    now_s = 1201.0  # noqa: F841  (lambda: now_s picks this up)

    # Step 8 — probe: send any pause command; expire_if_due fires first.
    out = list(agent.handle(_pause_msg("r-probe", ttl_s=60)))
    resumed_events = _maint_resumed_events(out)
    assert len(resumed_events) >= 1, "expected maint_resumed event after TTL expiry"
    assert resumed_events[0].payload.get("reason") == "ttl_expired"
    # Agent is now running (un-paused by TTL expiry), so the probe pause
    # should succeed as a fresh pause.
    assert _ack_accepted(out) is True
    assert _ack_reason(out) == "paused"
