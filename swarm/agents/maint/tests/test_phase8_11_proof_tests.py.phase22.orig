"""Phase 8 §8.11 — comprehensive proof tests.

Covers all four scenarios from the §8.11 proof-tests bullet:

(i)   Lag watchdog end-to-end: inject 6 s lag → tier-1 + sec.alert;
      ramp to 70 s → tier-3 + observer mode; clear lag → recovery event.
(ii)  No self-amplification: at-most-one tier-2 event per tier transition
      under sustained lag (no per-tick re-emission).
(iii) Own-DLQ growth-rate throttle: ~60 growth events in 60 s halves emit
      rate; confirm rate_factor > 0 (no immediate self-isolation, that is
      the §8.10 hard threshold).
(iv)  Bus circuit-breaker: kill the bus mid-emit → spool fills → restore
      bus → spool drains in arrival order.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest

from common import config as _cfg_mod
from ai.swarm.agents.maint._bus_circuit_breaker import (
    BusCircuitBreaker,
    _STATE_CLOSED,
    _STATE_DEGRADED,
)
from ai.swarm.agents.maint._dlq_throttle import DlqSelfThrottle
from ai.swarm.agents.maint._lag_watchdog import MaintLagWatchdog
from ai.swarm.agents.topics import MAINT_EVENT, SEC_ALERT
from ai.swarm.sdk.types import Message

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """Injectable monotonic clock (seconds, controllable in tests)."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


def _ms_counter(start: int = 1_000_000) -> Callable[[], int]:
    """Auto-incrementing millisecond counter — gives deterministic filename order."""
    counter = [start]

    def _next() -> int:
        counter[0] += 1
        return counter[0]

    return _next


def _msg(kind: str = "test_event", severity: str | None = None) -> Message:
    payload: dict = {"kind": kind, "request_id": str(uuid4())}
    if severity:
        payload["severity"] = severity
    return Message.new(topic=MAINT_EVENT, payload=payload, producer="maint.scaler.v1")


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def watchdog_cfg(monkeypatch):
    """Fast config: threshold=5 s, 1 s sustain window, 10 s recovery window."""
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_plane_lag_alert_ms", 5_000, raising=False)
    monkeypatch.setattr(c, "maint_plane_lag_alert_window_s", 1, raising=False)
    monkeypatch.setattr(c, "maint_plane_recovery_window_s", 10, raising=False)
    return c


@pytest.fixture()
def throttle_cfg(monkeypatch):
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_self_dlq_growth_alert", 50, raising=True)
    monkeypatch.setattr(c, "maint_self_dlq_throttle_recovery_s", 120, raising=True)
    return c


# ---------------------------------------------------------------------------
# (i) Lag watchdog — end-to-end scenario
# ---------------------------------------------------------------------------


def test_lag_watchdog_tier1_alert_on_6s_lag(watchdog_cfg):
    """Inject 6 s lag sustained > 1 s → tier-1; sec.alert{kind=maint_plane_lag_high}."""
    wd = MaintLagWatchdog()
    t = 0.0
    # Three observations of 6 s lag spaced 1 s apart → all in the 1 s window
    # after t=3, sustaining lag above the 5 s threshold.
    for _ in range(3):
        t += 1.0
        wd.note_lag(lag_s=6.0, now_s=t)
    msgs = wd.tick(now_s=t + 0.1)

    assert wd.tier == 1, f"Expected tier 1 after 6 s lag, got {wd.tier}"
    alert_kinds = [
        m.payload.get("kind")
        for m in msgs
        if m.envelope.topic == SEC_ALERT
    ]
    assert "maint_plane_lag_high" in alert_kinds, (
        f"Expected sec.alert maint_plane_lag_high at tier 1; got {alert_kinds}"
    )


def test_lag_watchdog_tier3_and_observer_mode_on_70s_lag(watchdog_cfg):
    """Ramp to 70 s lag → tier-3 throttled event; further ticks return [] (observer)."""
    wd = MaintLagWatchdog()
    t = 0.0
    for _ in range(3):
        t += 1.0
        wd.note_lag(lag_s=70.0, now_s=t)
    msgs = wd.tick(now_s=t + 0.1)

    assert wd.tier == 3, f"Expected tier 3 after 70 s lag, got {wd.tier}"
    tier3_events = [
        m for m in msgs
        if m.payload.get("kind") == "maint_plane_throttled"
        and m.payload.get("tier") == 3
    ]
    assert len(tier3_events) >= 1, (
        f"Expected maint_plane_throttled{{tier=3}}; got {msgs}"
    )
    # Observer mode: subsequent ticks under same lag emit nothing.
    follow_up = wd.tick(now_s=t + 1.0)
    assert follow_up == [], f"Expected no events in observer mode; got {follow_up}"


def test_lag_watchdog_recovery_event_after_tier3(watchdog_cfg):
    """After tier-3, clear lag for >= recovery_window_s → kind=maint_plane_recovered."""
    wd = MaintLagWatchdog()
    t = 0.0
    # Escalate to tier 3.
    for _ in range(3):
        t += 1.0
        wd.note_lag(lag_s=70.0, now_s=t)
    wd.tick(now_s=t + 0.1)
    assert wd.tier == 3

    # Clear lag below the recovery floor (1.0 s).
    t += 1.0
    wd.note_lag(lag_s=0.0, now_s=t)

    # Advance past recovery_window_s=10 s.
    t += 15.0
    recovery_msgs = wd.tick(now_s=t)

    recovered_kinds = [m.payload.get("kind") for m in recovery_msgs]
    assert "maint_plane_recovered" in recovered_kinds, (
        f"Expected maint_plane_recovered after lag clears; got {recovered_kinds}"
    )
    assert wd.tier == 0, f"Expected tier 0 after recovery, got {wd.tier}"


# ---------------------------------------------------------------------------
# (ii) No self-amplification — tier-2 at-most-once per transition
# ---------------------------------------------------------------------------


def test_no_self_amplification_tier2_at_most_once_under_sustained_lag(watchdog_cfg):
    """Sustained tier-2 lag → maint_plane_throttled{tier=2} emitted exactly once."""
    wd = MaintLagWatchdog()
    t = 0.0
    collected: list[Message] = []
    # Drive and sustain 20 s lag (> 15 s tier-2 threshold) for 10 seconds.
    for _ in range(20):
        t += 0.5
        wd.note_lag(lag_s=20.0, now_s=t)
        collected.extend(wd.tick(now_s=t + 0.05))

    tier2_events = [
        m for m in collected
        if m.payload.get("kind") == "maint_plane_throttled"
        and m.payload.get("tier") == 2
    ]
    assert len(tier2_events) == 1, (
        f"Self-amplification: expected exactly 1 tier-2 event, "
        f"got {len(tier2_events)} under sustained lag"
    )


# ---------------------------------------------------------------------------
# (iii) Own-DLQ growth-rate self-throttle
# ---------------------------------------------------------------------------


def test_sixty_growth_events_in_sixty_seconds_halves_emit_rate(throttle_cfg):
    """~60 entries of DLQ growth over 60 s (> 50/min threshold) → throttled, rate=0.5."""
    th = DlqSelfThrottle()
    t = 0.0
    # 7 samples 10 s apart, each adding 10 entries → growth ≈ 60/min > threshold 50.
    for i in range(7):
        t += 10.0
        th.note_depth(depth=i * 10, now_s=t)

    assert th.throttled is True, "Expected throttled after ~60 entries/min growth"
    assert th.rate_factor == 0.5, f"Expected rate_factor=0.5, got {th.rate_factor}"


def test_dlq_self_throttle_no_immediate_self_isolation(throttle_cfg):
    """DLQ self-throttle halves rate but rate_factor never reaches 0 (§8.10 owns isolation)."""
    th = DlqSelfThrottle()
    t = 0.0
    for i in range(7):
        t += 10.0
        th.note_depth(depth=i * 10, now_s=t)

    # §8.10 is the only path to self-isolation (rate_factor=0).
    assert th.rate_factor > 0.0, (
        f"DLQ self-throttle must NOT self-isolate; got rate_factor={th.rate_factor}"
    )
    assert th.rate_factor < 1.0, (
        f"DLQ self-throttle must have halved rate; got rate_factor={th.rate_factor}"
    )


# ---------------------------------------------------------------------------
# (iv) Bus circuit-breaker: spool fills then drains in newest-first order (§8.14.10)
# ---------------------------------------------------------------------------


def test_bus_circuit_breaker_spool_fills_and_drains_in_arrival_order(
    tmp_path: Path,
) -> None:
    """3 bus failures → breaker opens; subsequent emits spool; restore → drains newest-first (§8.14.10)."""
    call_count = [0]
    received_after_restore: list[Message] = []

    def _publish(m: Message) -> None:
        call_count[0] += 1
        # First 3 calls fail — trips the breaker on the 3rd.
        if call_count[0] <= 3:
            raise RuntimeError("bus down")
        # All subsequent calls succeed (probe + drain).
        received_after_restore.append(m)

    clock = _FakeClock(t=1000.0)
    spool_dir = tmp_path / "maint.scaler.v1"
    breaker = BusCircuitBreaker(
        agent_name="maint.scaler.v1",
        publish_fn=_publish,
        spool_dir=spool_dir,
        clock_ms=_ms_counter(),
        clock_s=clock,
        new_id=lambda: str(uuid4()),
        fail_threshold=3,
        fail_window_s=30.0,
    )

    # Three failures.  The 3rd failure opens the breaker and spools msg_c.
    breaker.publish(_msg("msg_a"))  # fail 1 — not spooled yet
    breaker.publish(_msg("msg_b"))  # fail 2 — not spooled yet
    breaker.publish(_msg("msg_c"))  # fail 3 — breaker opens; msg_c spooled
    assert breaker.state == _STATE_DEGRADED

    # Two more emits while degraded → spool entries 2 and 3 (arrival order).
    breaker.publish(_msg("msg_d"))
    breaker.publish(_msg("msg_e"))

    spool_files = sorted(spool_dir.glob("*.envelope.json"))
    assert len(spool_files) == 3, (
        f"Expected 3 spool entries (c, d, e), got {len(spool_files)}"
    )

    # Restore bus: tick() probes (succeeds), then drains in arrival order.
    drained = breaker.tick()

    assert breaker.state == _STATE_CLOSED, (
        f"Expected closed after successful probe; got {breaker.state}"
    )
    assert len(drained) == 3, (
        f"Expected 3 drained entries, got {len(drained)}: {drained}"
    )
    drained_kinds = [m.payload.get("kind") for m in drained]
    # §8.14.10 revised drain order: newest-first (mtime descending).
    # msg_c was spooled first (oldest), msg_e last (newest) → e, d, c.
    assert drained_kinds == ["msg_e", "msg_d", "msg_c"], (
        f"Spool must drain in newest-first (§8.14.10) order; got {drained_kinds}"
    )
    # Spool directory must be empty after a complete drain.
    remaining = list(spool_dir.glob("*.envelope.json"))
    assert remaining == [], (
        f"Spool not fully drained; {len(remaining)} files remain"
    )
