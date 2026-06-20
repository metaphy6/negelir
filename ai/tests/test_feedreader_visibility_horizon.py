"""Phase 16.4 §9 — Visibility horizon methods (ledger #34).

Tests for:
- FeedReader.visibility_horizon_ms(): Compute horizon from fsync_mode
- FeedReader.wait_for_visibility(): Block until wall-clock is observable

Binding test names per docs/design/phase16/sections/04-feedreader.md:
  - test_visibility_horizon_matches_fsync_mode.py
  - test_strict_caller_blocks_until_horizon.py
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from ai.common.feeds.reader import FeedReader


class TestVisibilityHorizonMs:
    """Tests for FeedReader.visibility_horizon_ms() (ledger #34)."""

    def test_visibility_horizon_always_mode_returns_zero(self) -> None:
        """fsync_mode='always' should return 0ms (visible immediately)."""
        reader = FeedReader(fsync_mode="always", fsync_batch_ms=100)
        assert reader.visibility_horizon_ms() == 0

    def test_visibility_horizon_batch_mode_returns_fsync_batch_ms(self) -> None:
        """fsync_mode='batch' should return fsync_batch_ms."""
        reader = FeedReader(fsync_mode="batch", fsync_batch_ms=200)
        assert reader.visibility_horizon_ms() == 200

    def test_visibility_horizon_batch_mode_custom_interval(self) -> None:
        """fsync_mode='batch' with custom fsync_batch_ms."""
        for batch_ms in [50, 100, 250, 500]:
            reader = FeedReader(fsync_mode="batch", fsync_batch_ms=batch_ms)
            assert reader.visibility_horizon_ms() == batch_ms

    def test_visibility_horizon_off_mode_returns_max_int(self) -> None:
        """fsync_mode='off' (test-only) should return 2^31 - 1."""
        reader = FeedReader(fsync_mode="off", fsync_batch_ms=100)
        assert reader.visibility_horizon_ms() == 2**31 - 1

    def test_visibility_horizon_invalid_mode_raises(self) -> None:
        """Invalid fsync_mode should raise ValueError."""
        reader = FeedReader(fsync_mode="invalid_mode", fsync_batch_ms=100)
        with pytest.raises(ValueError, match="Unknown fsync_mode"):
            reader.visibility_horizon_ms()


class TestWaitForVisibility:
    """Tests for FeedReader.wait_for_visibility() (ledger #34)."""

    def test_wait_for_visibility_always_mode_returns_immediately(self) -> None:
        """In 'always' mode, wait_for_visibility should return True immediately."""
        now = datetime.now(timezone.utc)
        captured_at = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        
        reader = FeedReader(fsync_mode="always")
        start = time.time()
        result = reader.wait_for_visibility(captured_at, timeout_ms=1000)
        elapsed_ms = (time.time() - start) * 1000
        
        assert result is True
        assert elapsed_ms < 100  # Should be almost instant

    def test_wait_for_visibility_batch_mode_blocks_until_horizon(self) -> None:
        """In 'batch' mode, wait_for_visibility should block until horizon is passed."""
        now = datetime.now(timezone.utc)
        # Record captured_at is in the future (relative to now)
        # So visibility_wall_clock = captured_at + horizon_ms
        future_dt = now + timedelta(milliseconds=150)
        captured_at = future_dt.isoformat().replace("+00:00", "Z")
        
        reader = FeedReader(fsync_mode="batch", fsync_batch_ms=100)
        start = time.time()
        result = reader.wait_for_visibility(captured_at, timeout_ms=1000)
        elapsed_ms = (time.time() - start) * 1000
        
        assert result is True
        # Should have blocked for ~150ms before returning
        # (the record is in the future, so we wait for captured_at + horizon)
        assert elapsed_ms >= 100  # At least horizon time

    def test_wait_for_visibility_timeout_returns_false(self) -> None:
        """If timeout is exceeded, wait_for_visibility should return False."""
        now = datetime.now(timezone.utc)
        # Create a wall-clock far in the future
        future_dt = now + timedelta(seconds=10)
        captured_at = future_dt.isoformat().replace("+00:00", "Z")
        
        reader = FeedReader(fsync_mode="batch", fsync_batch_ms=100)
        start = time.time()
        result = reader.wait_for_visibility(captured_at, timeout_ms=200)
        elapsed_ms = (time.time() - start) * 1000
        
        assert result is False
        # Should timeout after ~200ms
        assert 180 < elapsed_ms < 300

    def test_wait_for_visibility_invalid_timestamp_raises(self) -> None:
        """Invalid captured_at timestamp should raise ValueError."""
        reader = FeedReader(fsync_mode="always")
        
        with pytest.raises(ValueError, match="Could not parse captured_at"):
            reader.wait_for_visibility("not-a-valid-timestamp", timeout_ms=100)

    def test_wait_for_visibility_rfc3339_format(self) -> None:
        """wait_for_visibility should accept RFC3339 timestamps (Z suffix)."""
        now = datetime.now(timezone.utc)
        captured_at = now.isoformat().replace("+00:00", "Z")
        
        reader = FeedReader(fsync_mode="always")
        result = reader.wait_for_visibility(captured_at, timeout_ms=1000)
        
        assert result is True

    def test_wait_for_visibility_no_timeout_blocks_indefinitely(self) -> None:
        """Without timeout_ms, wait_for_visibility should block indefinitely.
        
        For this test, we use a recent past timestamp so it returns quickly,
        demonstrating that None timeout doesn't cause early return.
        """
        now = datetime.now(timezone.utc)
        past_dt = now - timedelta(seconds=5)
        captured_at = past_dt.isoformat().replace("+00:00", "Z")
        
        reader = FeedReader(fsync_mode="always")
        result = reader.wait_for_visibility(captured_at, timeout_ms=None)
        
        # Since captured_at is in the past and horizon is 0, it should return immediately
        assert result is True

    def test_wait_for_visibility_off_mode_with_long_timeout(self) -> None:
        """In 'off' mode (test-only), wait_for_visibility uses max visibility horizon."""
        now = datetime.now(timezone.utc)
        captured_at = now.isoformat().replace("+00:00", "Z")
        
        reader = FeedReader(fsync_mode="off")
        # With 'off' mode, horizon is huge, so it should timeout quickly
        start = time.time()
        result = reader.wait_for_visibility(captured_at, timeout_ms=100)
        elapsed_ms = (time.time() - start) * 1000
        
        # Should timeout because off mode has infinite horizon
        assert result is False
        assert elapsed_ms >= 100

