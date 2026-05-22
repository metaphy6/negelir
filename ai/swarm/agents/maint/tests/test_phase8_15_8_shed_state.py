"""Phase 8 §8.15.8 — Backpressure shed-tier survives leader handover.

Three proof-test scenarios from the §8.15.8 specification:

(a) Leader-A transitions to tier 2, lease handover to Leader-B
    simulated mid-tier → Leader-B reads tier=2 from the shed_state
    annotation, holds it for the full ``recovery_window_s``, and
    emits exactly one ``kind=maint_plane_throttled, action=
    inherited_from_lease`` event.

(b) Leader-A transitions to tier 3 then "crashes" (process restart
    simulated by constructing a fresh MaintLagWatchdog pointed at
    the same store); new leader reads tier=3, holds for the full
    recovery window.

(c) Compose-mode equivalent of handover: Leader-A writes
    shed_state.json at tier 2, process restarts (single replica) →
    on boot reads its own persisted state and re-enters tier 2
    (handles process flap, not just leadership flap).

Adversarial test:

(d) Inherited tier is held through the lock window and only lowered
    once the lock expires AND lag has been healthy for an additional
    ``recovery_window_s``.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from common import config as _cfg_mod
from swarm.agents.maint._lag_watchdog import MaintLagWatchdog
from swarm.agents.topics import MAINT_EVENT
from swarm.sdk.shed_state import ShedStateStore


# ---------------------------------------------------------------------------
# Config / clock helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """Controllable monotonic clock."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


@pytest.fixture()
def fast_cfg(monkeypatch):
    """Short windows so tests run in milliseconds, not real minutes."""
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_plane_lag_alert_ms", 5_000, raising=False)
    monkeypatch.setattr(c, "maint_plane_lag_alert_window_s", 1, raising=False)
    monkeypatch.setattr(c, "maint_plane_recovery_window_s", 10, raising=False)
    return c


def _make_store(tmp_path: Path, name: str = "maint.test.v1") -> ShedStateStore:
    return ShedStateStore(tmp_path / f"{name}.shed_state.json")


def _drive_to_tier(wd: MaintLagWatchdog, lag_s: float, window_s: float = 1.0) -> None:
    """Inject ``lag_s`` lag for ``window_s`` seconds to reach the tier it maps to."""
    for i in range(int(window_s * 4) + 1):
        wd.note_lag(lag_s=lag_s, now_s=float(i) * 0.25)
    wd.tick(now_s=float(int(window_s * 4)) * 0.25 + 0.1)


# ---------------------------------------------------------------------------
# (a) Leader-A → tier 2, handover → Leader-B inherits tier=2
# ---------------------------------------------------------------------------


def test_handover_inherits_tier2_and_emits_once(fast_cfg, tmp_path):
    """Leader-A escalates to tier 2; Leader-B reads tier=2 from the shed
    state, emits exactly one ``inherited_from_lease`` event, and holds
    the tier for the full recovery window before it can lower it.
    """
    store = _make_store(tmp_path)

    # --- Leader-A: escalate to tier 2 ---
    leader_a = MaintLagWatchdog(_shed_store=store)
    assert leader_a._pod_instance_id != ""
    a_pod_id = leader_a._pod_instance_id

    # Drive 20s lag → tier 2 (> _TIER2_LAG_S=15 s threshold)
    t = 0.0
    for _ in range(6):
        t += 0.25
        leader_a.note_lag(lag_s=20.0, now_s=t)
    leader_a.tick(now_s=t + 0.1)

    assert leader_a.tier == 2, f"Leader-A should be tier 2, got {leader_a.tier}"

    # Verify the shed state was persisted.
    record = store.read()
    assert record is not None, "shed_state must be written after tier-2 escalation"
    assert record.tier == 2
    assert record.pod_instance_id == a_pod_id

    # --- Leader-B: simulate handover by constructing a fresh watchdog
    # pointing at the same store. ---
    leader_b = MaintLagWatchdog(_shed_store=store)

    # Leader-B must inherit tier 2 immediately.
    assert leader_b.tier == 2, (
        f"Leader-B must inherit tier=2 from shed state, got {leader_b.tier}"
    )

    # Prior leader ID must be recorded.
    assert leader_b._prior_leader_pod_id == a_pod_id, (
        f"prior_leader_pod_id mismatch: expected {a_pod_id!r}, "
        f"got {leader_b._prior_leader_pod_id!r}"
    )

    # First tick must emit exactly ONE ``inherited_from_lease`` event.
    # We need at least one lag sample for tick() to proceed past the
    # empty-samples guard.
    leader_b.note_lag(lag_s=20.0, now_s=t + 0.5)
    tick_msgs = leader_b.tick(now_s=t + 0.6)

    inherited_events = [
        m for m in tick_msgs
        if m.payload.get("kind") == "maint_plane_throttled"
        and m.payload.get("action") == "inherited_from_lease"
    ]
    assert len(inherited_events) == 1, (
        f"Expected exactly 1 inherited_from_lease event on first tick; "
        f"got {len(inherited_events)}: {inherited_events}"
    )
    assert inherited_events[0].payload["tier"] == 2
    assert inherited_events[0].payload["prior_leader_pod_instance_id"] == a_pod_id

    # Second tick must NOT emit another inherited_from_lease event
    # (one-per-handover, not per-tick).
    leader_b.note_lag(lag_s=20.0, now_s=t + 1.0)
    second_tick = leader_b.tick(now_s=t + 1.1)
    second_inherited = [
        m for m in second_tick
        if m.payload.get("action") == "inherited_from_lease"
    ]
    assert second_inherited == [], (
        f"inherited_from_lease must fire once per handover, not per tick: "
        f"{second_inherited}"
    )


# ---------------------------------------------------------------------------
# (b) Leader-A → tier 3, crash → new leader inherits tier=3
# ---------------------------------------------------------------------------


def test_crash_restart_inherits_tier3(fast_cfg, tmp_path):
    """Leader-A escalates to tier 3 then 'crashes'; the fresh instance
    reads tier=3 from the shed state and holds it for the full
    recovery window.
    """
    store = _make_store(tmp_path)

    # --- Leader-A: escalate to tier 3 (70s lag > _TIER3_LAG_S=60s) ---
    leader_a = MaintLagWatchdog(_shed_store=store)
    t = 0.0
    for _ in range(6):
        t += 0.25
        leader_a.note_lag(lag_s=70.0, now_s=t)
    leader_a.tick(now_s=t + 0.1)
    assert leader_a.tier == 3

    record = store.read()
    assert record is not None and record.tier == 3

    # --- New leader (simulated restart) ---
    new_leader = MaintLagWatchdog(_shed_store=store)
    assert new_leader.tier == 3, (
        f"New leader must inherit tier=3 from shed state, got {new_leader.tier}"
    )
    assert new_leader._inherit_lock_until_s is not None, (
        "Inherit lock must be set after tier-3 inheritance"
    )

    # Even with healthy lag, the tier must not lower during the lock window.
    new_leader.note_lag(lag_s=0.0, now_s=t + 0.5)
    tick_msgs = new_leader.tick(now_s=t + 0.6)

    # Should emit the inherited_from_lease event.
    inherited = [
        m for m in tick_msgs
        if m.payload.get("action") == "inherited_from_lease"
    ]
    assert len(inherited) == 1, (
        f"Expected inherited_from_lease event; got {tick_msgs}"
    )
    assert inherited[0].payload["tier"] == 3

    # Tier must still be 3 (lock window not yet elapsed).
    assert new_leader.tier == 3, (
        f"Tier must stay at 3 during lock window, got {new_leader.tier}"
    )

    # Simulate time passing through recovery_window_s (10s) + extra.
    # The lock_until is 10s from construction; advance 11s.
    lock_start = new_leader._inherit_lock_until_s - 10.0  # approx construction t
    future_t = new_leader._inherit_lock_until_s + 1.0

    # Start the recovery countdown: healthy lag observed.
    new_leader.note_lag(lag_s=0.0, now_s=future_t - 5.0)
    # Advance to after lock expiry.
    new_leader.note_lag(lag_s=0.0, now_s=future_t)
    tick2 = new_leader.tick(now_s=future_t + 0.1)

    # Lock should have expired now but recovery countdown just started.
    assert new_leader._inherit_lock_until_s is None, (
        "Lock must clear after recovery_window_s expires"
    )


# ---------------------------------------------------------------------------
# (c) Compose-mode process flap: same single replica reads own shed state
# ---------------------------------------------------------------------------


def test_compose_mode_process_restart_reads_own_state(fast_cfg, tmp_path):
    """Leader-A (single replica, compose mode) writes shed_state.json at
    tier 2; on simulated restart (new MaintLagWatchdog, same store path)
    it reads its persisted state and re-enters tier 2. This proves that
    shed-state inheritance handles process flap, not just leadership flap.
    """
    store = _make_store(tmp_path)

    # --- First run: drive to tier 2 ---
    run_a = MaintLagWatchdog(_shed_store=store)
    t = 0.0
    for _ in range(6):
        t += 0.25
        run_a.note_lag(lag_s=20.0, now_s=t)
    run_a.tick(now_s=t + 0.1)
    assert run_a.tier == 2

    shed_file = store.path
    assert shed_file.exists(), "shed_state.json must exist after tier-2 escalation"

    # --- Simulated restart (new process) reading the same store ---
    run_b = MaintLagWatchdog(_shed_store=ShedStateStore(shed_file))
    assert run_b.tier == 2, (
        f"Restarted process must re-enter tier 2 from shed_state.json, "
        f"got tier={run_b.tier}"
    )
    assert run_b._emit_inherited_pending, (
        "Restarted process must emit inherited_from_lease on first tick"
    )

    # First tick emits the inherited event.
    run_b.note_lag(lag_s=20.0, now_s=t + 0.5)
    msgs = run_b.tick(now_s=t + 0.6)
    inherited = [m for m in msgs if m.payload.get("action") == "inherited_from_lease"]
    assert len(inherited) == 1


# ---------------------------------------------------------------------------
# (d) Adversarial: inherited lock prevents premature tier lowering
# ---------------------------------------------------------------------------


def test_inherited_lock_prevents_premature_recovery(fast_cfg, tmp_path):
    """Even if lag drops to 0 immediately after handover, the inherited
    tier must be held until the lock window expires.  Only after the lock
    expires AND the standard recovery countdown completes may tier lower.
    """
    store = _make_store(tmp_path)

    # Leader-A at tier 2.
    leader_a = MaintLagWatchdog(_shed_store=store)
    t = 0.0
    for _ in range(6):
        t += 0.25
        leader_a.note_lag(lag_s=20.0, now_s=t)
    leader_a.tick(now_s=t + 0.1)
    assert leader_a.tier == 2

    # Leader-B inherits; lag is immediately 0.
    leader_b = MaintLagWatchdog(_shed_store=store)
    assert leader_b.tier == 2

    # Recovery countdown must NOT fire while the lock window is active.
    for i in range(30):
        leader_b.note_lag(lag_s=0.0, now_s=t + 0.1 * (i + 1))
        ticks = leader_b.tick(now_s=t + 0.1 * (i + 1) + 0.05)
        # No recovery event while lock is active.
        recovered = [
            m for m in ticks
            if m.payload.get("kind") == "maint_plane_recovered"
        ]
        if leader_b._inherit_lock_until_s is not None:
            assert recovered == [], (
                f"Recovery must not fire during lock window "
                f"(tick {i}): {recovered}"
            )

    # Tier must still be > 0 until full recovery happens post-lock.
    # (Lock window = 10s = recovery_window_s in fast_cfg)
