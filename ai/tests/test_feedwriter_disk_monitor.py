"""Tests for disk usage monitoring and backpressure (Phase 16.2 bullet 7).

Covers:
  - Disk usage measurement with statvfs
  - Warning and block thresholds
  - Alert emission (feeds_disk_warn, feeds_disk_blocked)
  - Write blocking on high usage
  - Cache TTL for repeated checks
  - Statistics tracking
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from common.feeds.disk_monitor import DiskMonitor, DiskUsage
import time


class TestDiskUsage:
    """Tests for DiskUsage snapshot."""

    def test_disk_usage_creation(self):
        """DiskUsage captures all metrics."""
        usage = DiskUsage(
            total_bytes=1000000,
            used_bytes=800000,
            free_bytes=200000,
            usage_pct=80.0,
        )
        
        assert usage.total_bytes == 1000000
        assert usage.used_bytes == 800000
        assert usage.free_bytes == 200000
        assert usage.usage_pct == 80.0

    def test_disk_usage_is_stale_fresh(self):
        """Fresh snapshot is not stale."""
        usage = DiskUsage(
            total_bytes=1000000,
            used_bytes=800000,
            free_bytes=200000,
            usage_pct=80.0,
        )
        
        assert not usage.is_stale(cache_ttl_sec=10.0)

    def test_disk_usage_is_stale_old(self):
        """Old snapshot is stale."""
        usage = DiskUsage(
            total_bytes=1000000,
            used_bytes=800000,
            free_bytes=200000,
            usage_pct=80.0,
            captured_at_sec=time.time() - 10,
        )
        
        assert usage.is_stale(cache_ttl_sec=1.0)


class TestDiskMonitor:
    """Tests for DiskMonitor functionality."""

    def test_monitor_init_defaults(self):
        """DiskMonitor initializes with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir))
            
            assert monitor.warn_pct == 80.0
            assert monitor.block_pct == 95.0
            assert monitor.cache_ttl_sec == 1.0
            assert monitor.total_warns == 0
            assert monitor.total_blocks == 0

    def test_monitor_init_custom(self):
        """DiskMonitor accepts custom thresholds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(
                Path(tmpdir),
                warn_pct=70.0,
                block_pct=90.0,
                cache_ttl_sec=2.0,
            )
            
            assert monitor.warn_pct == 70.0
            assert monitor.block_pct == 90.0
            assert monitor.cache_ttl_sec == 2.0

    def test_monitor_get_usage_real(self):
        """get_usage returns real disk stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir))
            usage = monitor.get_usage()
            
            assert usage.total_bytes > 0
            assert usage.used_bytes >= 0
            assert usage.free_bytes >= 0
            assert 0 <= usage.usage_pct <= 100

    def test_monitor_get_usage_cache(self):
        """get_usage caches results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir), cache_ttl_sec=10.0)
            
            usage1 = monitor.get_usage()
            usage2 = monitor.get_usage()
            
            # Should be exact same object (cached)
            assert usage1 is usage2

    def test_monitor_get_usage_cache_refresh(self):
        """get_usage force_refresh bypasses cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir))
            
            usage1 = monitor.get_usage()
            usage2 = monitor.get_usage(force_refresh=True)
            
            # Different objects due to refresh
            assert usage1 is not usage2

    def test_monitor_check_disk_health_ok(self):
        """check_disk_health returns ok status when below thresholds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(
                Path(tmpdir),
                warn_pct=80.0,
                block_pct=95.0,
            )
            
            # Mock low usage
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=300,
                    free_bytes=700,
                    usage_pct=30.0,
                )
                
                health = monitor.check_disk_health()
                
                assert health["usage_pct"] == 30.0
                assert health["is_warning"] is False
                assert health["is_blocked"] is False
                assert health["status"] == "ok"

    def test_monitor_check_disk_health_warning(self):
        """check_disk_health returns warning status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(
                Path(tmpdir),
                warn_pct=80.0,
                block_pct=95.0,
            )
            
            # Mock warning usage
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=850,
                    free_bytes=150,
                    usage_pct=85.0,
                )
                
                health = monitor.check_disk_health()
                
                assert health["usage_pct"] == 85.0
                assert health["is_warning"] is True
                assert health["is_blocked"] is False
                assert health["status"] == "warning"
                assert monitor.total_warns == 1

    def test_monitor_check_disk_health_blocked(self):
        """check_disk_health returns blocked status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(
                Path(tmpdir),
                warn_pct=80.0,
                block_pct=95.0,
            )
            
            # Mock blocked usage
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=960,
                    free_bytes=40,
                    usage_pct=96.0,
                )
                
                health = monitor.check_disk_health()
                
                assert health["usage_pct"] == 96.0
                assert health["is_blocked"] is True
                assert health["status"] == "blocked"
                assert monitor.total_blocks == 1

    def test_monitor_can_write_ok(self):
        """can_write returns True when below block threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir), block_pct=95.0)
            
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=500,
                    free_bytes=500,
                    usage_pct=50.0,
                )
                
                assert monitor.can_write() is True

    def test_monitor_can_write_blocked(self):
        """can_write returns False when above block threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir), block_pct=95.0)
            
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=960,
                    free_bytes=40,
                    usage_pct=96.0,
                )
                
                assert monitor.can_write() is False

    def test_monitor_should_alert_none(self):
        """should_alert returns None when healthy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir))
            
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=500,
                    free_bytes=500,
                    usage_pct=50.0,
                )
                
                assert monitor.should_alert() is None

    def test_monitor_should_alert_warning(self):
        """should_alert returns feeds_disk_warn."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir), warn_pct=80.0)
            
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=850,
                    free_bytes=150,
                    usage_pct=85.0,
                )
                
                assert monitor.should_alert() == "feeds_disk_warn"

    def test_monitor_should_alert_blocked(self):
        """should_alert returns feeds_disk_blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir), block_pct=95.0)
            
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=960,
                    free_bytes=40,
                    usage_pct=96.0,
                )
                
                assert monitor.should_alert() == "feeds_disk_blocked"

    def test_monitor_get_stats(self):
        """get_stats returns comprehensive metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(
                Path(tmpdir),
                warn_pct=80.0,
                block_pct=95.0,
            )
            
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000000,
                    used_bytes=850000,
                    free_bytes=150000,
                    usage_pct=85.0,
                )
                
                monitor.total_warns = 5
                monitor.total_blocks = 2
                
                stats = monitor.get_stats()
                
                assert stats["total_bytes"] == 1000000
                assert stats["used_bytes"] == 850000
                assert stats["free_bytes"] == 150000
                assert stats["usage_pct"] == 85.0
                assert stats["warn_threshold_pct"] == 80.0
                assert stats["block_threshold_pct"] == 95.0
                assert stats["total_warnings"] == 5
                assert stats["total_blocks"] == 2


class TestDiskMonitorInvariants:
    """Property-based tests for disk monitor invariants."""

    def test_invariant_usage_pct_bounds(self):
        """Usage percentage is always 0-100."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir))
            
            for _ in range(10):
                usage = monitor.get_usage(force_refresh=True)
                assert 0 <= usage.usage_pct <= 100

    def test_invariant_usage_components(self):
        """Used + Free bytes <= Total bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(Path(tmpdir))
            usage = monitor.get_usage()
            
            assert usage.used_bytes + usage.free_bytes <= usage.total_bytes

    def test_invariant_alert_priority(self):
        """Blocked alert has priority over warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = DiskMonitor(
                Path(tmpdir),
                warn_pct=80.0,
                block_pct=95.0,
            )
            
            # Simulate very high usage (both warning and blocked apply)
            with patch.object(monitor, "get_usage") as mock_usage:
                mock_usage.return_value = DiskUsage(
                    total_bytes=1000,
                    used_bytes=970,
                    free_bytes=30,
                    usage_pct=97.0,
                )
                
                # should_alert should return blocked, not warning
                assert monitor.should_alert() == "feeds_disk_blocked"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
