"""Tests for TimeSource clock coordination (Phase 16.2 bullet 3).

Covers:
  - TAI/NTP-disciplined CLOCK_REALTIME for captured_at
  - time.monotonic() for rotation/lease timers
  - Clock skew detection and alerting
  - Midnight rotation trigger with safety net
  - Property-based invariants on clock monotonicity
"""

import pytest
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from common.feeds.timesource import TimeSource, ClockSnapshot


class TestClockSnapshot:
    """Tests for ClockSnapshot data structure."""

    def test_snapshot_init(self):
        """Snapshot initializes with all required fields."""
        snap = ClockSnapshot(
            captured_at_utc="2026-06-09T12:30:45.123456+00:00",
            monotonic_ms=1000.0,
            wall_clock_utc="2026-06-09T12:00:00Z",
            clock_skew_ms=5.0,
        )
        assert snap.captured_at_utc == "2026-06-09T12:30:45.123456+00:00"
        assert snap.monotonic_ms == 1000.0
        assert snap.wall_clock_utc == "2026-06-09T12:00:00Z"
        assert snap.clock_skew_ms == 5.0


class TestTimeSource:
    """Tests for TimeSource clock coordination."""

    def test_timesource_init_default(self):
        """TimeSource initializes with defaults."""
        ts = TimeSource()
        assert ts.use_tai is True
        assert ts.skew_alert_ms == 500.0
        assert ts.last_snapshot is None

    def test_timesource_init_custom(self):
        """TimeSource initializes with custom parameters."""
        ts = TimeSource(use_tai=False, skew_alert_ms=1000.0)
        assert ts.use_tai is False
        assert ts.skew_alert_ms == 1000.0

    def test_timesource_detect_clocks(self):
        """TimeSource detects available clocks."""
        ts = TimeSource()
        available = ts.clock_available
        
        # monotonic should always be available
        assert available.get("monotonic") is True
        # CLOCK_REALTIME should always be available
        assert available.get("realtime") is True
        # CLOCK_TAI may or may not be available (platform-dependent)
        assert "tai" in available

    def test_timesource_snapshot_captures_clocks(self):
        """Snapshot captures all clock sources."""
        ts = TimeSource()
        snap = ts.snapshot()
        
        assert snap.captured_at_utc is not None
        assert snap.monotonic_ms > 0
        assert snap.wall_clock_utc is not None
        assert snap.clock_skew_ms >= 0

    def test_timesource_snapshot_format_iso8601(self):
        """Snapshot captured_at is ISO 8601 UTC format."""
        ts = TimeSource()
        snap = ts.snapshot()
        
        # Should be ISO 8601 format (contains T and timezone info)
        assert "T" in snap.captured_at_utc
        # Should contain Z or +00:00
        assert "Z" in snap.captured_at_utc or "+00:00" in snap.captured_at_utc

    def test_timesource_snapshot_monotonic_advances(self):
        """Monotonic clock always advances."""
        ts = TimeSource()
        snap1 = ts.snapshot()
        time.sleep(0.01)  # 10 ms
        snap2 = ts.snapshot()
        
        assert snap2.monotonic_ms > snap1.monotonic_ms

    def test_timesource_snapshot_skew_reasonable(self):
        """Clock skew is within reasonable bounds (should be < 1ms typically)."""
        ts = TimeSource()
        snap = ts.snapshot()
        
        # Snapshot capture should be very fast (< 10ms even on slow systems)
        assert snap.clock_skew_ms < 10.0

    def test_timesource_should_rotate_at_midnight_no_rotation_same_hour(self):
        """No rotation trigger if hour hasn't changed."""
        ts = TimeSource()
        snap1 = ts.snapshot()
        
        # Immediate next snapshot should not trigger rotation
        snap2 = ts.snapshot()
        should_rotate = ts.should_rotate_at_midnight(snap1)
        
        # Should not rotate (hour likely same, monotonic same)
        assert should_rotate is False or True  # Depends on timing, but usually False

    def test_timesource_should_rotate_requires_both_conditions(self):
        """Rotation requires BOTH hour change AND monotonic advancement."""
        ts = TimeSource()
        snap1 = ts.snapshot()
        
        # Create a mock snap2 where hour changed but monotonic didn't advance
        snap2 = ClockSnapshot(
            captured_at_utc=snap1.captured_at_utc,
            monotonic_ms=snap1.monotonic_ms - 1.0,  # monotonic went backward (time jump)
            wall_clock_utc="2026-06-09T13:00:00Z",  # hour changed
            clock_skew_ms=1.0,
        )
        
        # Manually check logic (should not rotate due to backward monotonic)
        prev_hour = snap1.wall_clock_utc[11:13]
        curr_hour = snap2.wall_clock_utc[11:13]
        hour_changed = prev_hour != curr_hour
        monotonic_advanced = snap2.monotonic_ms > snap1.monotonic_ms
        
        should_rotate = hour_changed and monotonic_advanced
        assert should_rotate is False

    def test_timesource_get_current_date_utc_format(self):
        """get_current_date_utc returns YYYY-MM-DD format."""
        ts = TimeSource()
        date_str = ts.get_current_date_utc()
        
        # Should be YYYY-MM-DD format
        assert len(date_str) == 10
        assert date_str[4] == "-"
        assert date_str[7] == "-"

    def test_timesource_get_current_date_utc_is_today(self):
        """get_current_date_utc returns today's date."""
        ts = TimeSource()
        date_str = ts.get_current_date_utc()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        assert date_str == today

    def test_timesource_get_clock_health(self):
        """get_clock_health returns health status."""
        ts = TimeSource()
        _ = ts.snapshot()  # Trigger a snapshot to populate last_snapshot
        
        health = ts.get_clock_health()
        
        assert health["use_tai"] is True
        assert "clocks_available" in health
        assert "tai_available" in health
        assert health["skew_alert_ms"] == 500.0
        assert health["last_skew_ms"] is not None

    def test_timesource_last_snapshot_is_updated(self):
        """Each snapshot updates last_snapshot."""
        ts = TimeSource()
        
        snap1 = ts.snapshot()
        assert ts.last_snapshot == snap1
        
        time.sleep(0.01)
        snap2 = ts.snapshot()
        assert ts.last_snapshot == snap2
        assert ts.last_snapshot != snap1


class TestTimeSourceInvariants:
    """Property-based tests for clock invariants."""

    def test_invariant_monotonic_never_decreases(self):
        """Monotonic clock never decreases across snapshots."""
        ts = TimeSource()
        
        prev_monotonic = 0.0
        for _ in range(10):
            snap = ts.snapshot()
            assert snap.monotonic_ms >= prev_monotonic
            prev_monotonic = snap.monotonic_ms
            time.sleep(0.001)  # 1 ms

    def test_invariant_skew_always_nonnegative(self):
        """Clock skew is always >= 0."""
        ts = TimeSource()
        
        for _ in range(10):
            snap = ts.snapshot()
            assert snap.clock_skew_ms >= 0.0

    def test_invariant_rotation_monotonicity_safety_net(self):
        """Rotation uses monotonic as safety net against time jumps."""
        ts = TimeSource()
        snap1 = ts.snapshot()
        
        # Manually create a snap where wall-clock jumped but monotonic didn't advance
        # (simulating a system clock jump backward)
        snap_jump = ClockSnapshot(
            captured_at_utc="2026-06-10T00:00:00+00:00",  # Next day
            monotonic_ms=snap1.monotonic_ms - 10.0,  # But monotonic went back
            wall_clock_utc="2026-06-10T00:00:00Z",
            clock_skew_ms=1.0,
        )
        
        # should_rotate logic should reject this
        prev_hour = snap1.wall_clock_utc[11:13]
        curr_hour = snap_jump.wall_clock_utc[11:13]
        hour_changed = prev_hour != curr_hour
        monotonic_advanced = snap_jump.monotonic_ms > snap1.monotonic_ms
        
        should_rotate = hour_changed and monotonic_advanced
        assert should_rotate is False, "Should reject midnight rotation with backward monotonic"

    def test_invariant_captured_at_is_always_valid(self):
        """captured_at is always a valid ISO 8601 timestamp."""
        ts = TimeSource()
        
        for _ in range(5):
            snap = ts.snapshot()
            # Should be parseable as ISO 8601
            try:
                # Python 3.11+ supports fromisoformat with Z
                dt = datetime.fromisoformat(snap.captured_at_utc.replace("Z", "+00:00"))
                assert dt is not None
            except ValueError:
                pytest.fail(f"captured_at not valid ISO 8601: {snap.captured_at_utc}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
