"""Phase 8 §8.9 DoD — maint plane lag watchdog proof tests.

Bullet:
  Inject 6s consumer lag on ``maint.event.v1`` → tier-1 shedding + 1 alert.
  Ramp to 70s → tier-3 observer mode + 1 alert.
  Clear → 1 recovery event.
  Assert at most 1 event per tier transition (no per-tick re-emission).
"""

from __future__ import annotations

import pytest

from common import config as _cfg_mod
from swarm.agents.maint._lag_watchdog import MaintLagWatchdog


@pytest.fixture()
def cfg(monkeypatch):
    """Compress time windows so tests remain instant and deterministic."""
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_plane_lag_alert_ms", 5_000, raising=True)
    monkeypatch.setattr(c, "maint_plane_lag_alert_window_s", 1, raising=True)
    monkeypatch.setattr(c, "maint_plane_recovery_window_s", 1, raising=True)
    return c


# ---------------------------------------------------------------------------
# Tier-1 shedding on 6s lag
# ---------------------------------------------------------------------------


def test_tier1_alert_on_6s_lag(cfg):
    """6s lag sustained for the window → exactly 1 sec.alert.v1 (maint_plane_lag_high)."""
    wdog = MaintLagWatchdog()
    # Feed observations at t=0 and t=1 (> window_s=1) so _lag_sustained_for passes.
    wdog.note_lag(6.0, now_s=0.0)
    wdog.note_lag(6.0, now_s=1.0)
    msgs = wdog.tick(now_s=1.5)
    lag_high = [m for m in msgs if m.payload.get("kind") == "maint_plane_lag_high"]
    assert len(lag_high) == 1, f"Expected 1 lag_high alert, got {len(lag_high)}: {msgs}"
    assert lag_high[0].payload["severity"] == "warn"
    assert lag_high[0].payload["tier"] == 1


def test_tier1_sets_watchdog_tier(cfg):
    """After tier-1 trigger, watchdog.tier == 1."""
    wdog = MaintLagWatchdog()
    wdog.note_lag(6.0, now_s=0.0)
    wdog.note_lag(6.0, now_s=1.0)
    wdog.tick(now_s=1.5)
    assert wdog.tier == 1


def test_below_threshold_emits_nothing(cfg):
    """Lag below 5s threshold emits no events."""
    wdog = MaintLagWatchdog()
    wdog.note_lag(3.0, now_s=0.0)
    wdog.note_lag(3.0, now_s=1.0)
    assert wdog.tick(now_s=1.5) == []
    assert wdog.tier == 0


# ---------------------------------------------------------------------------
# No per-tick re-emission
# ---------------------------------------------------------------------------


def test_tier1_alert_emitted_only_once(cfg):
    """Calling tick() repeatedly at tier-1 emits the alert exactly once total."""
    wdog = MaintLagWatchdog()
    wdog.note_lag(6.0, now_s=0.0)
    wdog.note_lag(6.0, now_s=1.0)

    all_msgs: list = []
    for i in range(5):
        wdog.note_lag(6.0, now_s=1.5 + i * 0.5)
        all_msgs.extend(wdog.tick(now_s=1.5 + i * 0.5))

    lag_high = [m for m in all_msgs if m.payload.get("kind") == "maint_plane_lag_high"]
    assert len(lag_high) == 1, f"Expected exactly 1 alert over 5 ticks, got {len(lag_high)}"


# ---------------------------------------------------------------------------
# Tier-3 observer mode on 70s lag
# ---------------------------------------------------------------------------


def test_tier3_throttled_event_on_70s_lag(cfg):
    """70s lag → exactly 1 maint_plane_throttled{tier=3} event.

    §8.11: ramping through tier-2 also emits maint_plane_throttled{tier=2} once,
    so we filter to tier=3 specifically.
    """
    wdog = MaintLagWatchdog()
    # Establish tier 1 first (6s, sustain window).
    wdog.note_lag(6.0, now_s=0.0)
    wdog.note_lag(6.0, now_s=1.0)
    wdog.tick(now_s=1.5)

    # Ramp to 70s.
    wdog.note_lag(70.0, now_s=2.0)
    wdog.note_lag(70.0, now_s=3.0)
    msgs = wdog.tick(now_s=3.5)

    # §8.11: tier-2 also emits maint_plane_throttled{tier=2} on first entry.
    tier3_throttled = [
        m for m in msgs
        if m.payload.get("kind") == "maint_plane_throttled" and m.payload.get("tier") == 3
    ]
    assert len(tier3_throttled) == 1, f"Expected 1 tier-3 throttled event: {msgs}"
    assert tier3_throttled[0].payload["tier"] == 3


def test_tier3_sets_watchdog_tier(cfg):
    """After tier-3 trigger, watchdog.tier == 3."""
    wdog = MaintLagWatchdog()
    wdog.note_lag(70.0, now_s=0.0)
    wdog.note_lag(70.0, now_s=1.0)
    wdog.tick(now_s=1.5)
    assert wdog.tier == 3


def test_tier3_emits_only_one_event_over_multiple_ticks(cfg):
    """Repeated ticks at tier-3 lag produce maint_plane_throttled{tier=3} exactly once.

    §8.11: ramping through tier-2 produces one tier-2 event; tier-3 must also
    fire exactly once regardless of how many ticks are called at sustained lag.
    """
    wdog = MaintLagWatchdog()
    wdog.note_lag(70.0, now_s=0.0)
    wdog.note_lag(70.0, now_s=1.0)

    all_msgs: list = []
    for i in range(5):
        wdog.note_lag(70.0, now_s=1.5 + i * 0.5)
        all_msgs.extend(wdog.tick(now_s=1.5 + i * 0.5))

    tier3_throttled = [
        m for m in all_msgs
        if m.payload.get("kind") == "maint_plane_throttled" and m.payload.get("tier") == 3
    ]
    assert len(tier3_throttled) == 1, (
        f"Expected exactly 1 tier-3 throttled event over multiple ticks: {all_msgs}"
    )


# ---------------------------------------------------------------------------
# Recovery event after lag clears
# ---------------------------------------------------------------------------


def test_recovery_event_after_lag_clear(cfg):
    """After tier-3, clearing lag produces exactly 1 maint_plane_recovered event."""
    wdog = MaintLagWatchdog()
    # Reach tier 3.
    wdog.note_lag(70.0, now_s=0.0)
    wdog.note_lag(70.0, now_s=1.0)
    wdog.tick(now_s=1.5)
    assert wdog.tier == 3

    # Clear lag: drop below recovery floor for the window.
    wdog.note_lag(0.0, now_s=2.0)
    wdog.note_lag(0.0, now_s=3.0)
    msgs = wdog.tick(now_s=3.5)

    recovered = [m for m in msgs if m.payload.get("kind") == "maint_plane_recovered"]
    assert len(recovered) == 1
    assert wdog.tier == 0


def test_recovery_resets_emitted_tiers(cfg):
    """After recovery, re-entering tier 1 emits the alert again (fresh state)."""
    wdog = MaintLagWatchdog()
    # First cycle: reach tier 1, then recover.
    wdog.note_lag(6.0, now_s=0.0)
    wdog.note_lag(6.0, now_s=1.0)
    wdog.tick(now_s=1.5)
    assert wdog.tier == 1

    wdog.note_lag(0.0, now_s=2.0)
    wdog.note_lag(0.0, now_s=3.0)
    wdog.tick(now_s=3.5)
    assert wdog.tier == 0  # recovered

    # Second cycle: tier 1 again — must emit a fresh alert.
    wdog.note_lag(6.0, now_s=10.0)
    wdog.note_lag(6.0, now_s=11.0)
    msgs = wdog.tick(now_s=11.5)
    lag_high = [m for m in msgs if m.payload.get("kind") == "maint_plane_lag_high"]
    assert len(lag_high) == 1


# ---------------------------------------------------------------------------
# No recovery before the window elapses
# ---------------------------------------------------------------------------


def test_no_recovery_before_window(cfg, monkeypatch):
    """Lag clearing for < recovery_window_s does NOT emit maint_plane_recovered."""
    # Extend the recovery window so 0.5s is clearly not enough.
    monkeypatch.setattr(_cfg_mod.cfg, "maint_plane_recovery_window_s", 10, raising=True)
    wdog = MaintLagWatchdog()
    wdog.note_lag(70.0, now_s=0.0)
    wdog.note_lag(70.0, now_s=1.0)
    wdog.tick(now_s=1.5)

    # Clear lag — starts recovery countdown but window (10s) hasn't elapsed.
    wdog.note_lag(0.0, now_s=2.0)
    msgs = wdog.tick(now_s=2.5)  # only 0.5s since clear start
    recovered = [m for m in msgs if m.payload.get("kind") == "maint_plane_recovered"]
    assert len(recovered) == 0
    assert wdog.tier == 3  # still in tier 3


# ---------------------------------------------------------------------------
# Direct tier-0 → tier-3 jump (no intermediate step)
# ---------------------------------------------------------------------------


def test_direct_jump_tier0_to_tier3_emits_both_tier1_and_tier3(cfg):
    """Lag jumps directly from 0 to 70s → tier-1 alert + tier-3 throttled (2 events)."""
    wdog = MaintLagWatchdog()
    wdog.note_lag(70.0, now_s=0.0)
    wdog.note_lag(70.0, now_s=1.0)
    msgs = wdog.tick(now_s=1.5)

    kinds = [m.payload.get("kind") for m in msgs]
    assert "maint_plane_lag_high" in kinds
    assert "maint_plane_throttled" in kinds
    assert wdog.tier == 3
