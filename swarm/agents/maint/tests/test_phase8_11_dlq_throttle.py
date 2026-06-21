"""Phase 8 §8.11 — per-agent DLQ growth-rate self-throttle tests.

Verifies :class:`DlqSelfThrottle`:
  * Happy path: growth below threshold → not throttled, rate_factor 1.0.
  * Happy path: growth above threshold → throttled, rate_factor 0.5.
  * Recovery: growth non-positive for < recovery_s → still throttled.
  * Recovery: growth non-positive for >= recovery_s → throttle lifts.
  * Adversarial: rapid growth trips throttle immediately.
  * Adversarial: recovery countdown resets on positive growth spike.
  * Adversarial: fewer than 2 samples in window → never throttled.
  * Adversarial: no self-isolation (rate_factor only halves, not zero).
"""
from __future__ import annotations

import pytest

from common import config as _cfg_mod
from swarm.agents.maint._dlq_throttle import DlqSelfThrottle


@pytest.fixture()
def throttle_cfg(monkeypatch):
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_self_dlq_growth_alert", 50, raising=True)
    monkeypatch.setattr(c, "maint_self_dlq_throttle_recovery_s", 120, raising=True)
    return c


# ---------------------------------------------------------------------------
# Happy path — below threshold
# ---------------------------------------------------------------------------


def test_no_throttle_below_threshold(throttle_cfg):
    """Growth below threshold → throttled=False, rate_factor=1.0."""
    th = DlqSelfThrottle()
    # 10 entries/min growth (threshold=50) — should NOT throttle.
    t = 0.0
    for i in range(6):
        t += 10.0
        th.note_depth(depth=i * 1, now_s=t)  # ~0.1 entries/s = 6/min

    assert th.throttled is False
    assert th.rate_factor == 1.0


def test_throttle_above_threshold(throttle_cfg):
    """Growth > 50 entries/min → throttled=True, rate_factor=0.5."""
    th = DlqSelfThrottle()
    # Feed 100 entries of growth over 60 seconds = 100/min (> 50).
    t = 0.0
    for i in range(7):
        t += 10.0
        th.note_depth(depth=i * 17, now_s=t)  # ~17 every 10s = 102/min

    assert th.throttled is True
    assert th.rate_factor == 0.5


# ---------------------------------------------------------------------------
# Recovery path
# ---------------------------------------------------------------------------


def test_recovery_requires_full_window(throttle_cfg):
    """Throttle stays active when non-positive growth lasts < recovery_s."""
    th = DlqSelfThrottle()
    t = 0.0

    # Trip the throttle (rapid growth).
    for i in range(6):
        t += 10.0
        th.note_depth(depth=i * 20, now_s=t)  # 20/10s = 120/min

    assert th.throttled is True

    # Growth drops to zero — depth stays flat for 60 s (< 120 s recovery).
    last_depth = th._samples[-1][1]
    for _ in range(6):
        t += 10.0
        th.note_depth(depth=last_depth, now_s=t)

    # Only 60 s of non-positive — throttle should still be active.
    assert th.throttled is True, "Throttle must remain active before recovery window"


def test_recovery_lifts_after_full_window(throttle_cfg):
    """Throttle lifts after non-positive growth for the full recovery window."""
    th = DlqSelfThrottle()
    t = 0.0

    # Trip the throttle: 6 ticks × 10s → t=60, depth=100 (growth ≈ 100/min).
    for i in range(6):
        t += 10.0
        th.note_depth(depth=i * 20, now_s=t)

    assert th.throttled is True

    # Hold depth flat.  The 60-second growth window only turns zero at
    # t=120 (when the window no longer contains the ramp).  From there
    # recovery needs another 120 s → first chance at t=240.
    # 19 ticks × 10s: t goes from 70 → 250, which crosses t=240.
    last_depth = th._samples[-1][1]
    for _ in range(19):
        t += 10.0
        th.note_depth(depth=last_depth, now_s=t)

    assert th.throttled is False, "Throttle must lift after full recovery window"
    assert th.rate_factor == 1.0


# ---------------------------------------------------------------------------
# Adversarial — rapid growth trips immediately
# ---------------------------------------------------------------------------


def test_rapid_growth_trips_throttle_immediately(throttle_cfg):
    """A sudden large depth jump engages throttle on the very next note_depth."""
    th = DlqSelfThrottle()
    t = 0.0
    # One depth=0 seed, then immediate jump to 200 (200/min > 50).
    th.note_depth(depth=0, now_s=0.0)
    th.note_depth(depth=200, now_s=30.0)  # 200 over 30s = 400/min

    assert th.throttled is True
    assert th.rate_factor == 0.5


def test_recovery_countdown_resets_on_positive_spike(throttle_cfg):
    """A positive growth spike during recovery resets the countdown."""
    th = DlqSelfThrottle()
    t = 0.0

    # Trip throttle.
    for i in range(6):
        t += 10.0
        th.note_depth(depth=i * 20, now_s=t)
    assert th.throttled is True

    # 60 s of flat → recovery countdown starts.
    last_depth = th._samples[-1][1]
    for _ in range(6):
        t += 10.0
        th.note_depth(depth=last_depth, now_s=t)

    # Positive spike — restart countdown.
    th.note_depth(depth=last_depth + 10, now_s=t + 1.0)
    non_positive_before = th._non_positive_since
    assert non_positive_before is None, (
        "Recovery countdown must reset when growth turns positive again"
    )
    # Throttle still active.
    assert th.throttled is True


# ---------------------------------------------------------------------------
# Adversarial — too few samples
# ---------------------------------------------------------------------------


def test_single_sample_never_throttles(throttle_cfg):
    """A single depth observation cannot produce a growth rate."""
    th = DlqSelfThrottle()
    th.note_depth(depth=9999, now_s=0.0)
    assert th.throttled is False


def test_no_self_isolation_rate_never_zero(throttle_cfg):
    """Throttle only halves the rate — rate_factor is never below 0.5."""
    th = DlqSelfThrottle()
    # Drive extreme growth.
    th.note_depth(depth=0, now_s=0.0)
    th.note_depth(depth=100_000, now_s=1.0)
    # Rate factor must be exactly 0.5 (not 0 or negative).
    assert th.rate_factor == 0.5, (
        f"rate_factor must be 0.5 under throttle, got {th.rate_factor}"
    )
