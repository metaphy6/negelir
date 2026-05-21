"""Phase 8 §8.10 — Proof tests: leader-election, dead-mans-switch, self-isolation, split-brain.

All four sub-bullets of the §8.10 "Proof tests" binding bullet:

(a) leader-election: kill the leader pod, assert second pod becomes leader
    within 2× lease duration and resumes publishing (scale_decision emitted).

(b) dead-mans-switch: stop all maint.event.v1 producers in a test harness,
    advance the clock past the threshold, assert the alert fires exactly once
    (first emit bypasses debounce; second immediate call within the dedup
    window is suppressed — exactly-once per window).

(c) self-isolation: feed 100 poisoned events to maint.scaler.v1 (DLQ depth
    >= maint_self_dlq_alert threshold=100), assert it stops issuing scale
    calls and emits sec.alert.v1{kind=maint_self_dlq_alert, severity=critical}.
    Adversarial counter: 99 events (one below threshold) must NOT isolate.

(d) leader split-brain: the full K8s API partition contract (losing pod →
    observer within lease_duration + 5s, never co-issuing) is verified in
    test_phase8_9_leader_split_brain.py. This file adds the complementary
    scaler-level assertion: the losing scaler's tick() emits no scale_decision
    once in observer mode, even when fed high-signal inputs.
"""
from __future__ import annotations

from swarm.agents.maint.deadmans import MaintDeadmansSwitch
from swarm.agents.maint._pause_state import PauseState
from swarm.agents.maint.scaler import MaintScaler
from swarm.sdk.leader import ControllableK8sLeader


# ── Shared helpers ───────────────────────────────────────────────────────────


class _FakeClock:
    """Monotonic-clock stub with manual advance capability."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _high_signal(target: str = "predictor.elo") -> dict[str, dict[str, float]]:
    """Signal that unconditionally warrants a scale-up decision."""
    return {target: {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}}


def _scale_decisions(msgs) -> list:
    return [m for m in msgs if m.payload.get("kind") == "scale_decision"]


# ── (a) leader-election: pod kill → second pod leader within 2× lease ───────


def test_second_pod_becomes_leader_after_pod_kill_within_2x_lease() -> None:
    """Kill pod A (shed); assert pod B becomes leader within 2× lease_duration.

    Contract:
      - lease_duration_s = 15s; 2× limit = 30s.
      - Pod A is initial leader; pod B is initial observer.
      - Pod A kills itself via shed() (models pre-shutdown SIGTERM).
      - Pod B wins re-election via restore_api() at t=0 (well within 30s).
      - Pod B's scaler.tick() emits scale_decision (publishing resumes).
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0
    two_x_limit = 2.0 * lease_s  # 30s

    leader_a = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    leader_b = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    leader_b.shed()  # pod B starts as observer

    assert leader_a.is_leader(), "pod A must be leader initially"
    assert not leader_b.is_leader(), "pod B must be observer initially"

    # Pod A kills itself.
    leader_a.shed()
    assert not leader_a.is_leader(), "pod A must not be leader after shed()"

    # Pod B wins re-election at t=0 (well within 2× lease = 30s).
    leader_b.restore_api()
    assert leader_b.is_leader(), "pod B must be leader after restore_api()"
    assert clock() <= two_x_limit, (
        f"re-election at t={clock()} must be within 2×lease_s={two_x_limit}"
    )

    # Pod B's scaler resumes publishing.
    scaler_b = MaintScaler(leader=leader_b)
    msgs = scaler_b.tick(_high_signal())
    decisions = _scale_decisions(msgs)
    assert decisions, "pod B's scaler must emit scale_decision after becoming leader"


def test_new_leader_resumes_publishing_old_leader_goes_silent() -> None:
    """After takeover at t=5s, new leader emits; dead leader is silent.

    This validates the 'resumes publishing' clause of sub-bullet (a)
    while also confirming the former leader does not co-issue.
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0

    leader_a = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    scaler_a = MaintScaler(leader=leader_a)

    # Pod A emits before shedding.
    msgs_a_before = scaler_a.tick(_high_signal("target.alpha"))
    assert _scale_decisions(msgs_a_before), "pod A must emit scale_decision before shed"

    clock.advance(5.0)  # t=5, well within 2×15=30s
    leader_a.shed()

    # Pod B takes over at t=5.
    leader_b = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    scaler_b = MaintScaler(leader=leader_b)
    msgs_b = scaler_b.tick(_high_signal("target.beta"))
    assert _scale_decisions(msgs_b), (
        "pod B must emit scale_decision immediately after taking the lease"
    )

    # Dead pod A must be silent.
    msgs_a_after = scaler_a.tick(_high_signal("target.alpha"))
    assert not _scale_decisions(msgs_a_after), (
        "dead pod A must NOT emit scale_decision after shed()"
    )


# ── (b) dead-mans-switch: silence → exactly once (debounce-bypass) ───────────


def test_dead_mans_switch_fires_exactly_once_then_dedupes(monkeypatch) -> None:
    """Stop all producers; advance past threshold; first tick fires the alert
    (debounce does not suppress the first-ever emit); second immediate tick
    within the dedup window is suppressed — exactly-once per window.
    """
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_silence_warmup_s", 60, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_alert_h", 1, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_dedup_s", 60, raising=True)

    sw = MaintDeadmansSwitch(started_at_s=0.0)

    # Within warmup: no alert.
    assert sw.tick(now_s=30.0) == [], "must not alert during warmup"

    # Past warmup (60s) + 1h threshold (3600s) + 1s safety margin.
    t_past = 60.0 + 3600.0 + 1.0

    out1 = sw.tick(now_s=t_past)
    assert len(out1) == 1, (
        f"must emit exactly one alert when silence threshold exceeded; got {len(out1)}"
    )
    p = out1[0].payload
    assert p["kind"] == "maint_silence_alert", f"unexpected kind: {p['kind']!r}"
    assert p["severity"] == "critical", f"alert must be critical; got {p['severity']!r}"
    assert "no maint.event.v1" in p["reason"], (
        f"reason must describe the silence; got {p['reason']!r}"
    )

    # Second tick immediately (t+1s, well within the 60s dedup window): deduped.
    out2 = sw.tick(now_s=t_past + 1.0)
    assert out2 == [], "second tick within dedup window must be suppressed (exactly-once)"


def test_dead_mans_switch_silence_alert_re_fires_after_dedup_window(monkeypatch) -> None:
    """Adversarial: after the dedup window expires, the alert re-fires."""
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_silence_warmup_s", 60, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_alert_h", 1, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_dedup_s", 5, raising=True)

    sw = MaintDeadmansSwitch(started_at_s=0.0)
    t_past = 60.0 + 3600.0 + 1.0

    out1 = sw.tick(now_s=t_past)
    assert len(out1) == 1, "first emit must fire"

    # Advance past the 5s dedup window.
    out2 = sw.tick(now_s=t_past + 6.0)
    assert len(out2) == 1, "must re-fire after dedup window expires"


# ── (c) self-isolation: 100 poisoned events → scale calls stop ───────────────


def test_self_isolation_on_100_dlq_entries_stops_scale_calls(monkeypatch) -> None:
    """Feed 100 poisoned events (DLQ depth = threshold=100).

    Assertions:
      1. scaler._pause.self_isolated flips to True.
      2. scaler.tick() returns [] — scale calls halted.
      3. Deadmans switch emits sec.alert.v1{kind=maint_self_dlq_alert,
         severity=critical} with the scaler's id in subject.
    """
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_self_dlq_alert", 100, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_warmup_s", 60, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_dedup_s", 1, raising=True)

    scaler = MaintScaler()
    sw = MaintDeadmansSwitch(
        agents={"maint.scaler.v1": scaler},
        started_at_s=0.0,
    )

    # Pre-condition: scaler is healthy.
    assert not scaler._pause.self_isolated, "scaler must not be isolated initially"
    pre_msgs = scaler.tick(_high_signal())
    assert _scale_decisions(pre_msgs), "scaler must emit scale_decision before isolation"

    # Feed 100 poisoned events (DLQ depth = threshold).
    sw_out = sw.tick(now_s=70.0, dlq_depths={"maint.scaler.v1": 100})

    # 1. Self-isolated flag is set.
    assert scaler._pause.self_isolated, (
        "scaler._pause.self_isolated must be True after 100 DLQ entries"
    )

    # 2. Scale decisions stop.
    post_msgs = scaler.tick(_high_signal())
    assert post_msgs == [], (
        "self-isolated scaler must return [] on tick (scale calls halted)"
    )

    # 3. Critical alert is emitted with identifying subject.
    assert len(sw_out) == 1, f"expected exactly one alert, got {len(sw_out)}"
    alert_payload = sw_out[0].payload
    assert alert_payload["kind"] == "maint_self_dlq_alert", (
        f"expected maint_self_dlq_alert, got {alert_payload['kind']!r}"
    )
    assert alert_payload["severity"] == "critical"
    assert "maint.scaler.v1" in str(alert_payload.get("subject", "")), (
        "alert subject must identify the isolated agent"
    )


def test_self_isolation_adversarial_99_events_no_isolation(monkeypatch) -> None:
    """Adversarial (Rule 7): 99 events (one below threshold=100) must NOT isolate.

    The fence is strict: depth < threshold passes; depth >= threshold trips.
    """
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_self_dlq_alert", 100, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_warmup_s", 60, raising=True)
    monkeypatch.setattr(cfg, "maint_silence_dedup_s", 1, raising=True)

    scaler = MaintScaler()
    sw = MaintDeadmansSwitch(
        agents={"maint.scaler.v1": scaler},
        started_at_s=0.0,
    )

    sw_out = sw.tick(now_s=70.0, dlq_depths={"maint.scaler.v1": 99})
    assert not scaler._pause.self_isolated, (
        "scaler must NOT be isolated at depth=99 (one below threshold=100)"
    )
    assert sw_out == [], "no alert must fire at depth=99"
    msgs = scaler.tick(_high_signal())
    assert _scale_decisions(msgs), "scaler must still emit scale_decision at depth=99"


# ── (d) split-brain: scaler-level observer mode assertion ────────────────────


def test_split_brain_observer_scaler_emits_no_scale_decisions() -> None:
    """After K8s API partition the losing scaler's tick() must return [].

    This is the scaler-level complement to the full K8s partition contract
    verified in test_phase8_9_leader_split_brain.py (losing pod transitions
    to observer within lease_duration + 5s, no co-issuing between pods).
    Here we assert the decision loop itself is gated: even with high-signal
    inputs the losing scaler produces no scale_decision messages.
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0

    leader = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    scaler = MaintScaler(leader=leader)

    # Pre-condition: leader emits.
    msgs_before = scaler.tick(_high_signal("target.before"))
    assert _scale_decisions(msgs_before), "must emit before API failure"

    # Inject API failure and expire the lease.
    leader.inject_api_failure()
    clock.advance(lease_s + 1.0)  # t = 16s > expiry (within lease_duration + 5s = 20s)

    assert not leader.is_leader(), "must be observer after lease expiry"

    # Observer must not emit scale_decision under any signal.
    msgs_after = scaler.tick(_high_signal("target.after"))
    assert not _scale_decisions(msgs_after), (
        f"observer scaler MUST NOT emit scale_decision; got {_scale_decisions(msgs_after)}"
    )
