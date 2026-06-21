"""Phase 8.9 DoD — Leader split-brain proof tests.

Bullet (binding):
  Block K8s API (coordination.k8s.io/v1 503); assert losing pod
  transitions to observer within `lease_duration + 5s` BEFORE
  attempting any publish.  Restore API; assert exactly one leader
  resumes, no duplicate `scale_decision` for the overlap window.

Mechanism:
  :class:`~swarm.sdk.leader.ControllableK8sLeader` is a test double
  that mimics the real K8s lease protocol: it holds a time-based
  expiry renewed via ``tick_renewal()``.  Calling
  ``inject_api_failure()`` stops renewals; advancing the injected
  clock past ``expiry`` makes ``is_leader()`` return False.

  MaintScaler's ``tick()`` checks ``is_leader()`` before every emit;
  a non-leader tick returns an empty list (observer mode).

Contract verified:
  1. After API failure, the losing pod is in observer mode within
     ``lease_duration_s`` (the expiry window) — strictly before
     ``lease_duration_s + 5s``.  The scaler emits no
     ``scale_decision`` messages once in observer mode.
  2. After API restore, exactly one leader resumes.  The post-restore
     pod emits ``scale_decision`` messages; the still-expired pod
     does not.  The decision_window_ids produced by the new leader do
     not overlap with those produced by the old leader before the
     split, so no duplicate rows on ``(agent, decision_window_id)``.
"""
from __future__ import annotations

from swarm.agents.maint.scaler import MaintScaler
from swarm.sdk.leader import ControllableK8sLeader


# ── helpers ──────────────────────────────────────────────────────


class _FakeClock:
    """Monotonic-clock stub with manual advance capability."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _high_signal(target: str = "predictor.elo") -> dict[str, dict[str, float]]:
    return {target: {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}}


# ── Test 1: losing pod transitions to observer before lease + 5s ──


def test_losing_pod_is_observer_after_api_failure_within_lease_duration() -> None:
    """Losing pod must NOT emit scale_decision once the lease expires.

    Setup:
      lease_duration_s = 15; clock starts at t=0.
      Scaler A holds the lease (is_leader() True at t=0).
      inject_api_failure() at t=0 → renewals stop.

    Step 1 (t=0): tick → scale_decision emitted (still leader).
    Step 2 (t=10, mid-lease): tick → still emits (lease intact).
    Step 3 (t=16, lease_duration + 1s): tick → observer, no emit.
      This is well within lease_duration + 5s = 20s.

    Binding contract: is_leader() must return False BEFORE
    lease_duration + 5s elapses with no successful renewal.
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0
    leader = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    scaler = MaintScaler(leader=leader)

    # t=0: initially leader, should emit scale_decision
    msgs_t0 = scaler.tick(_high_signal())
    decisions_t0 = [m for m in msgs_t0 if m.payload.get("kind") == "scale_decision"]
    assert decisions_t0, "must emit scale_decision when leader at t=0"

    # Inject API failure at t=0 (no more renewals)
    leader.inject_api_failure()

    # t=10: still within lease_duration_s (15s) → still leader
    clock.advance(10.0)
    assert leader.is_leader(), "lease must still be held at t=10 < lease_duration=15"

    # t=16: one second past expiry → observer
    clock.advance(6.0)  # total = 16s
    assert not leader.is_leader(), (
        "losing pod must be in observer mode at t=16 "
        "(lease_duration=15s expired; well within lease_duration+5s=20s)"
    )

    # Scaler tick in observer mode → no scale_decision
    msgs_observer = scaler.tick(_high_signal())
    decisions_observer = [
        m for m in msgs_observer if m.payload.get("kind") == "scale_decision"
    ]
    assert not decisions_observer, (
        "observer pod MUST NOT emit scale_decision after lease expiry; "
        f"got {decisions_observer}"
    )


def test_observer_transition_strictly_before_lease_plus_5s() -> None:
    """Observer transition happens at exactly lease_duration_s, strictly
    before the lease_duration + 5s deadline.

    This test probes the boundary: at t = lease_duration_s - epsilon
    the pod is still leader; at t = lease_duration_s it is observer.
    Both must hold BEFORE the t = lease_duration_s + 5s worst-case.
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0
    leader = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )

    leader.inject_api_failure()  # stop renewals immediately

    # Just before expiry: still leader
    clock.advance(lease_s - 0.001)
    assert leader.is_leader(), "must still be leader just before lease expiry"

    # At expiry: observer
    clock.advance(0.002)  # now = lease_s + 0.001
    assert not leader.is_leader(), (
        "must be in observer mode at the lease expiry boundary"
    )

    # Confirm this happened at <= lease_duration + 5s
    assert clock() <= lease_s + 5.0, (
        f"observer transition at t={clock()} is past the "
        f"lease_duration+5s={lease_s + 5.0} deadline"
    )


# ── Test 2: restore API → exactly one leader, no duplicate window ids ──


def test_restore_api_exactly_one_leader_resumes() -> None:
    """After API restore, exactly one pod is leader.

    Setup:
      Pod A: initial leader; inject_api_failure → expires.
      Pod B: initial observer (shed); restore_api → becomes leader.

    Assertion: pod_A.is_leader() False, pod_B.is_leader() True.
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0

    # Pod A is the initial leader.
    leader_a = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )

    # Pod B starts as an observer (shed immediately).
    leader_b = ControllableK8sLeader(
        name="maint.scaler.v1",
        lease_duration_s=lease_s,
        clock=clock,
    )
    leader_b.shed()  # B is not leader initially

    # Both pods share the same clock.
    assert leader_a.is_leader(), "pod A must be leader initially"
    assert not leader_b.is_leader(), "pod B must be observer initially"

    # API goes down; pod A stops renewing.
    leader_a.inject_api_failure()

    # Advance clock past pod A's lease expiry.
    clock.advance(lease_s + 1.0)

    assert not leader_a.is_leader(), "pod A must be observer after lease expires"
    assert not leader_b.is_leader(), "pod B still has no lease (shed, never renewed)"

    # API restored; pod B wins re-election (first to call restore_api).
    leader_b.restore_api()

    assert leader_b.is_leader(), "pod B must be leader after restore_api"
    assert not leader_a.is_leader(), "pod A must remain observer (still API-failed)"

    # Exactly one leader.
    leaders = [leader_a.is_leader(), leader_b.is_leader()]
    assert leaders.count(True) == 1, (
        f"exactly one leader must hold the lease; got {leaders}"
    )


def test_no_duplicate_scale_decision_window_ids_across_leadership_transition() -> None:
    """No ``(agent, decision_window_id)`` duplicate across leadership transition.

    Pre-failure: pod A emits scale_decisions (recorded in pre_ids).
    Post-transition: pod B emits scale_decisions (recorded in post_ids).
    Contract: pre_ids ∩ post_ids == ∅ (Postgres dedup key safe).
    """
    clock = _FakeClock(start=0.0)
    lease_s = 15.0

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
    leader_b.shed()

    scaler_a = MaintScaler(leader=leader_a)
    scaler_b = MaintScaler(leader=leader_b)

    # Collect pre-failure decision window ids from pod A.
    pre_msgs = scaler_a.tick(_high_signal())
    pre_ids = {
        m.payload["decision_window_id"]
        for m in pre_msgs
        if m.payload.get("kind") == "scale_decision"
    }
    assert pre_ids, "pod A must emit at least one scale_decision before failure"

    # Simulate split-brain: API goes down, lease expires for pod A.
    leader_a.inject_api_failure()
    clock.advance(lease_s + 1.0)

    assert not leader_a.is_leader(), "pod A must be observer post-expiry"

    # Pod B wins re-election.
    leader_b.restore_api()
    assert leader_b.is_leader()

    # Collect post-transition decision window ids from pod B.
    post_msgs = scaler_b.tick(_high_signal())
    post_ids = {
        m.payload["decision_window_id"]
        for m in post_msgs
        if m.payload.get("kind") == "scale_decision"
    }
    assert post_ids, "pod B must emit at least one scale_decision after takeover"

    # Core assertion: no overlap on the Postgres dedup key.
    overlap = pre_ids & post_ids
    assert not overlap, (
        f"decision_window_id collision between pre-failure pod A "
        f"and post-takeover pod B: {overlap}"
    )

    # Pod A must emit nothing in observer mode.
    observer_msgs = scaler_a.tick(_high_signal())
    observer_decisions = [
        m for m in observer_msgs if m.payload.get("kind") == "scale_decision"
    ]
    assert not observer_decisions, (
        "pod A must not emit scale_decision while in observer mode"
    )
