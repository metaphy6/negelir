"""Tests for FeedWriter manifest atomicity (Phase 16.2, bullet 9).

Tests verify:
  - Manifest write-tmp + rename + fsync(parent_dir) atomic pattern
  - No partial manifest files visible to readers
  - Crash safety: manifest reflects last successful write
  - Metrics fields tracked: disk_usage_pct, clock_skew_ms, fairness violations, parts_per_date
  - Lease holder field updated atomically
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai.common.feeds.writer import FeedWriter, FeedManifest


@pytest.fixture
def temp_feeds_dir():
    """Temporary directory for test feed files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    client = MagicMock()
    client.set.return_value = True
    client.get.return_value = b"test-writer-1"
    return client


class TestManifestAtomicity:
    """Atomic manifest write tests."""
    
    def test_atomic_manifest_write_tmp_rename_pattern(self, temp_feeds_dir, mock_redis):
        """Manifest is written to .tmp file first, then atomically renamed."""
        writer = FeedWriter(
            plane="reference",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-1",
        )
        writer.open()
        
        # Enqueue a record to update manifest state
        record = {"record_type": "reference", "source": "mackolik", "data": "test"}
        writer.enqueue(record)
        
        # Get manifest path
        manifest_path = writer.partition_dir / "manifest.json"
        tmp_path = manifest_path.with_suffix(".json.tmp")
        
        # Manually trigger manifest save
        writer._save_manifest()
        
        # After save, tmp file should not exist (atomic rename completed)
        assert not tmp_path.exists()
        assert manifest_path.exists()
        
        # Manifest should be valid JSON
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["plane"] == "reference"
            assert data["source"] == "mackolik"
        
        writer.close()
    
    def test_manifest_no_partial_file_visible_to_readers(self, temp_feeds_dir, mock_redis):
        """Readers never see a partial/corrupted manifest due to rename atomicity."""
        writer = FeedWriter(
            plane="score",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-2",
        )
        writer.open()
        
        manifest_path = writer.partition_dir / "manifest.json"
        
        # Save manifest multiple times
        for i in range(5):
            writer.manifest.records_written = i * 100
            writer._save_manifest()
            
            # Verify manifest is always valid (no partial reads)
            assert manifest_path.exists()
            with open(manifest_path) as f:
                data = json.load(f)
                assert data["records_written"] == i * 100
        
        writer.close()
    
    def test_manifest_tracks_disk_usage_pct(self, temp_feeds_dir, mock_redis):
        """Manifest update_manifest_metrics() records disk_usage_pct."""
        writer = FeedWriter(
            plane="market",
            source="tff",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-3",
        )
        writer.open()
        
        # Update with disk usage metric
        writer.update_manifest_metrics(disk_usage_pct=85.5)
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["disk_usage_pct"] == 85.5
        
        writer.close()
    
    def test_manifest_tracks_clock_skew_ms(self, temp_feeds_dir, mock_redis):
        """Manifest update_manifest_metrics() records clock_skew_ms."""
        writer = FeedWriter(
            plane="lineup",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-4",
        )
        writer.open()
        
        # Update with clock skew
        writer.update_manifest_metrics(clock_skew_ms=150)
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["clock_skew_ms"] == 150
        
        writer.close()
    
    def test_manifest_tracks_fairness_floor_violations(self, temp_feeds_dir, mock_redis):
        """Manifest update_manifest_metrics() records fairness floor violations."""
        writer = FeedWriter(
            plane="editorial",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-5",
        )
        writer.open()
        
        # Update with fairness violations count
        writer.update_manifest_metrics(fairness_floor_violations_window=3)
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["fairness_floor_violations_window"] == 3
        
        writer.close()
    
    def test_manifest_tracks_parts_per_date(self, temp_feeds_dir, mock_redis):
        """Manifest update_manifest_metrics() records partition counts per date."""
        writer = FeedWriter(
            plane="reference",
            source="tff",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-6",
        )
        writer.open()
        
        # Update with partition counts
        parts_map = {
            "2026-06-09": 1,
            "2026-06-08": 3,
            "2026-06-07": 2,
        }
        writer.update_manifest_metrics(parts_per_date=parts_map)
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["parts_per_date"] == parts_map
        
        writer.close()
    
    def test_manifest_records_lease_holder(self, temp_feeds_dir, mock_redis):
        """Manifest update_manifest_metrics() records current lease holder."""
        mock_redis.get.return_value = b"lease-holder-xyz"
        
        writer = FeedWriter(
            plane="schedule",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-7",
        )
        writer.open()
        
        # Update metrics (should read current lease holder from Redis)
        writer.update_manifest_metrics(disk_usage_pct=50.0)
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["writer_lease_holder"] == "lease-holder-xyz"
        
        writer.close()
    
    def test_manifest_atomic_update_all_fields(self, temp_feeds_dir, mock_redis):
        """All metrics can be updated in one atomic operation."""
        mock_redis.get.return_value = b"current-holder"
        
        writer = FeedWriter(
            plane="reference",
            source="openfootball",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-8",
        )
        writer.open()
        
        # Update all metrics at once
        writer.update_manifest_metrics(
            disk_usage_pct=72.3,
            clock_skew_ms=42,
            fairness_floor_violations_window=2,
            parts_per_date={"2026-06-09": 1},
        )
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["disk_usage_pct"] == 72.3
            assert data["clock_skew_ms"] == 42
            assert data["fairness_floor_violations_window"] == 2
            assert data["parts_per_date"] == {"2026-06-09": 1}
            assert data["writer_lease_holder"] == "current-holder"
        
        writer.close()
    
    def test_manifest_partial_update_preserves_existing_fields(self, temp_feeds_dir, mock_redis):
        """Partial updates don't overwrite fields not specified."""
        writer = FeedWriter(
            plane="score",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-9",
        )
        writer.open()
        
        # First update: set some fields
        writer.update_manifest_metrics(
            disk_usage_pct=60.0,
            clock_skew_ms=100,
            fairness_floor_violations_window=5,
        )
        
        # Second update: only update disk usage
        writer.update_manifest_metrics(disk_usage_pct=65.0)
        
        manifest_path = writer.partition_dir / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
            assert data["disk_usage_pct"] == 65.0
            # These should still have their previous values
            assert data["clock_skew_ms"] == 100
            assert data["fairness_floor_violations_window"] == 5
        
        writer.close()
    
    def test_manifest_fsync_parent_directory(self, temp_feeds_dir, mock_redis):
        """Manifest save calls fsync on parent directory for durability."""
        with patch("os.fsync") as mock_fsync, \
             patch("os.open", return_value=3) as mock_open, \
             patch("os.close") as mock_close:
            
            writer = FeedWriter(
                plane="editorial",
                source="mackolik",
                feeds_dir=str(temp_feeds_dir),
                redis_client=mock_redis,
                writer_id="test-writer-10",
            )
            writer.open()
            writer._save_manifest()
            
            # Verify os.fsync was called
            assert mock_fsync.called
            # Verify fd was opened and closed
            assert mock_open.called
            assert mock_close.called
            
            writer.close()
    
    def test_manifest_recovery_after_crash(self, temp_feeds_dir, mock_redis):
        """Manifest can be recovered after a crash; no partial files."""
        writer1 = FeedWriter(
            plane="market",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="writer-crashed",
        )
        writer1.open()
        
        # Write some data and update metrics
        record = {"data": "test"}
        writer1.enqueue(record)
        writer1.update_manifest_metrics(disk_usage_pct=55.0, clock_skew_ms=75)
        
        manifest_path = writer1.partition_dir / "manifest.json"
        
        # "Crash" - just get the last manifest state before closing
        with open(manifest_path) as f:
            crashed_manifest = json.load(f)
        
        # Recover: open new writer for same plane/source
        mock_redis.get.return_value = b"recovered-writer"
        writer2 = FeedWriter(
            plane="market",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="recovered-writer",
        )
        writer2.open()
        
        # Manifest should be loaded correctly (no corruption)
        assert writer2.manifest.disk_usage_pct == 55.0
        assert writer2.manifest.clock_skew_ms == 75
        assert writer2.manifest.plane == "market"
        assert writer2.manifest.source == "nesine"
        
        writer2.close()
    
    def test_manifest_tmp_cleanup_on_write_error(self, temp_feeds_dir, mock_redis):
        """Temporary manifest file is cleaned up if write fails."""
        writer = FeedWriter(
            plane="lineup",
            source="tff",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-11",
        )
        writer.open()
        
        # Make partition_dir read-only to force write failure
        partition_dir = writer.partition_dir
        os.chmod(partition_dir, 0o444)
        
        try:
            # This should fail but clean up temp file
            with pytest.raises(Exception):
                writer._save_manifest()
            
            # Restore permissions to verify cleanup
            os.chmod(partition_dir, 0o755)
            
            # Verify no .tmp file is left behind
            tmp_path = writer.manifest_path.with_suffix(".json.tmp")
            assert not tmp_path.exists()
        finally:
            # Restore permissions for cleanup
            os.chmod(partition_dir, 0o755)
            writer.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
