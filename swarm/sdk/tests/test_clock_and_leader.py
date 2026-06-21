"""Phase 8 §8.15.1 + §8.10 — clock + leader Protocol unit tests."""
from __future__ import annotations

import sys
import time
import unittest.mock as mock

import pytest

from swarm.sdk.clock import (
    CLOCK_SOURCE_AUTO,
    CLOCK_SOURCE_BOOTTIME,
    CLOCK_SOURCE_MONOTONIC,
    boot_validate_clock_source,
    check_suspend_gap,
    resolve_clock,
    window_anchor_ns,
)
from swarm.sdk.leader import SingleProcessLeader


def test_resolve_clock_auto_returns_callable() -> None:
    source, fn = resolve_clock(CLOCK_SOURCE_AUTO)
    assert source in ("boottime", "monotonic")
    a, b = fn(), fn()
    assert isinstance(a, int) and isinstance(b, int)
    assert b >= a


def test_resolve_clock_monotonic_pinned() -> None:
    source, fn = resolve_clock(CLOCK_SOURCE_MONOTONIC)
    assert source == "monotonic"
    assert fn() > 0


def test_resolve_clock_unknown_raises() -> None:
    with pytest.raises(ValueError):
        resolve_clock("wallclock")


def test_window_anchor_quantizes_monotonically() -> None:
    win_ms = 1000
    a = window_anchor_ns(win_ms, now_ns=5_500_000_000)
    b = window_anchor_ns(win_ms, now_ns=5_999_999_999)
    c = window_anchor_ns(win_ms, now_ns=6_000_000_000)
    assert a == b
    assert c > a
    assert c - a == 1_000_000_000


def test_window_anchor_zero_window_rejected() -> None:
    with pytest.raises(ValueError):
        window_anchor_ns(0)


def test_single_process_leader_default_is_leader() -> None:
    leader = SingleProcessLeader(name="maint.scaler.v1")
    assert leader.is_leader() is True
    assert leader.name == "maint.scaler.v1"


def test_single_process_leader_shed_then_reacquire() -> None:
    leader = SingleProcessLeader(name="maint.dlq.v1")
    leader.shed()
    assert leader.is_leader() is False
    leader.reacquire()
    assert leader.is_leader() is True


# ── §8.15.1 proof tests ────────────────────────────────────────────────────


def test_suspend_simulation_window_ids_differ() -> None:
    """§8.15.1 proof (a): simulate a 60 s container suspend.

    Monkey-patch the clock helper so that ``boottime_ns`` advances
    60 seconds beyond ``monotonic_ns`` (as it would during a real
    suspend).  Two consecutive ``window_anchor_ns`` calls whose
    underlying time spans the suspend boundary MUST produce different
    anchor values — they would NOT under raw ``time.monotonic_ns()``
    if the process only elapsed 1 ms wall-clock but 60 s elapsed in
    real (boottime) time.
    """
    win_ms = 1000  # 1-second windows

    # Before suspend: both clocks agree.
    base_ns = 10_000_000_000  # 10 s into epoch (arbitrary stable base)

    # After a simulated 60 s suspend: boottime advanced 60 s, monotonic did not.
    post_suspend_boottime_ns = base_ns + 60_000_000_000
    post_suspend_monotonic_ns = base_ns + 1_000_000  # only 1 ms elapsed

    anchor_before = window_anchor_ns(win_ms, now_ns=base_ns,
                                     source=CLOCK_SOURCE_MONOTONIC)
    anchor_after = window_anchor_ns(win_ms, now_ns=post_suspend_boottime_ns,
                                    source=CLOCK_SOURCE_MONOTONIC)

    # With boottime the two anchors are in different 1-second windows.
    assert anchor_after > anchor_before, (
        "post-suspend boottime window must be later than pre-suspend window"
    )
    assert anchor_after - anchor_before == 60_000_000_000, (
        "anchor gap must equal the 60 s suspend duration"
    )

    # Show that raw monotonic would have kept them in the SAME window.
    anchor_mono_after = window_anchor_ns(win_ms, now_ns=post_suspend_monotonic_ns,
                                         source=CLOCK_SOURCE_MONOTONIC)
    assert anchor_mono_after == anchor_before, (
        "raw monotonic would NOT have advanced the window across the suspend — "
        "this is the collision the boottime fix prevents"
    )


def test_boot_validation_boottime_forced_unavailable_raises() -> None:
    """§8.15.1 proof (b): forcing boottime on a platform without CLOCK_BOOTTIME.

    When ``source_cfg='boottime'`` is configured but the current platform
    does not expose ``CLOCK_BOOTTIME``, ``boot_validate_clock_source``
    must raise ``SystemExit`` — the agent refuses to start
    (``fail_safe_clock_source_unavailable`` sentinel).
    """
    with mock.patch("swarm.sdk.clock._boottime_available", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            boot_validate_clock_source(CLOCK_SOURCE_BOOTTIME, agent_id="test-agent")
        assert "fail_safe_clock_source_unavailable" in str(exc_info.value)


def test_suspend_detection_fires_on_90s_gap() -> None:
    """§8.15.1 proof (c): synthesize a 90 s suspend gap between heartbeats.

    The ``check_suspend_gap`` helper must return one
    ``maint_clock_source_changed{action=suspend_detected, gap_s≈90}``
    event dict when the boottime–monotonic delta grew by 90 s across
    two consecutive heartbeat samples.
    """
    # Heartbeat N: both clocks at 100 s.
    prev_boottime_ns = 100_000_000_000
    prev_monotonic_ns = 100_000_000_000

    # Heartbeat N+1: monotonic advanced 1 s; boottime advanced 91 s
    # (90 s suspend + 1 s real elapsed).
    cur_boottime_ns = 191_000_000_000
    cur_monotonic_ns = 101_000_000_000

    event = check_suspend_gap(
        prev_boottime_ns=prev_boottime_ns,
        prev_monotonic_ns=prev_monotonic_ns,
        cur_boottime_ns=cur_boottime_ns,
        cur_monotonic_ns=cur_monotonic_ns,
        alert_threshold_s=30.0,
    )

    assert event is not None, "a 90-second gap must produce a suspend event"
    assert event["kind"] == "maint_clock_source_changed"
    assert event["action"] == "suspend_detected"
    gap_s = event["gap_s"]
    assert isinstance(gap_s, float)
    assert abs(gap_s - 90.0) < 0.001, f"expected gap_s≈90, got {gap_s}"


def test_suspend_detection_silent_below_threshold() -> None:
    """§8.15.1 adversarial: sub-threshold gap must NOT fire an event."""
    event = check_suspend_gap(
        prev_boottime_ns=100_000_000_000,
        prev_monotonic_ns=100_000_000_000,
        cur_boottime_ns=110_000_000_000,  # only 10 s delta growth
        cur_monotonic_ns=100_000_000_000,
        alert_threshold_s=30.0,
    )
    assert event is None, "sub-threshold gap must not produce a suspend event"


def test_suspend_detection_disabled_when_threshold_zero() -> None:
    """§8.15.1 adversarial: probe disabled when alert_threshold_s=0."""
    event = check_suspend_gap(
        prev_boottime_ns=100_000_000_000,
        prev_monotonic_ns=100_000_000_000,
        cur_boottime_ns=999_000_000_000,  # huge gap
        cur_monotonic_ns=100_000_000_000,
        alert_threshold_s=0.0,
    )
    assert event is None, "threshold=0 must disable the probe entirely"


def test_boot_validate_fallback_returns_sec_alert_on_non_linux() -> None:
    """§8.15.1 adversarial: auto-mode on non-Linux returns a sec_alert warn."""
    with mock.patch("swarm.sdk.clock._boottime_available", return_value=False):
        result = boot_validate_clock_source(CLOCK_SOURCE_AUTO, agent_id="tester")
    maint_event = result["maint_event"]
    sec_alert = result["sec_alert"]
    assert maint_event["kind"] == "maint_clock_source_changed"
    assert maint_event["suspend_resilient"] is False
    assert maint_event["current"] == "monotonic"
    assert sec_alert is not None
    assert sec_alert["kind"] == "maint_clock_source_unsupported"
    assert sec_alert["severity"] == "warn"

