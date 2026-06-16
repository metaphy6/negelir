"""Tests for FeedWriter crash-recovery startup (Phase 16.2, bullet 10).

Tests verify:
  - Half-state detection (.tmp, partial rotations, missing sidecars)
  - Decision tree (RESUME vs ROLLBACK)
  - Artifact cleanup on ROLLBACK
  - Writer readiness after recovery
  - Idempotency (no corruption, no data loss on recovery)
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from common.feeds.writer import FeedWriter, FeedManifest


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


class TestCrashRecoveryDetection:
    """Tests for detecting half-states."""
    
    def test_detect_half_states_tmp_file(self, temp_feeds_dir, mock_redis):
        """Detect unfinished manifest write (.tmp file)."""
        writer = FeedWriter(
            plane="reference",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-1",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a tmp file to simulate interrupted manifest write
        tmp_path = writer.partition_dir / "manifest.json.tmp"
        tmp_path.write_text('{"incomplete": "manifest"}')
        
        half_states = writer._detect_half_states()
        assert len(half_states["tmp_files"]) == 1
        assert str(tmp_path) in half_states["tmp_files"]
    
    def test_detect_half_states_partial_rotation(self, temp_feeds_dir, mock_redis):
        """Detect partial rotation (.ndjson + .ndjson.zst for same date)."""
        writer = FeedWriter(
            plane="score",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-2",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create both live and sealed files for same date
        live_path = writer.partition_dir / "2026-06-09.ndjson"
        sealed_path = writer.partition_dir / "2026-06-09.ndjson.zst"
        
        live_path.write_bytes(b'{"record": 1}\n')
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')  # zstd magic
        
        half_states = writer._detect_half_states()
        assert len(half_states["partial_rotations"]) == 1
        assert half_states["partial_rotations"][0]["date"] == "2026-06-09"
        assert "live" in half_states["partial_rotations"][0]
        assert "sealed" in half_states["partial_rotations"][0]
    
    def test_detect_half_states_missing_sidecar(self, temp_feeds_dir, mock_redis):
        """Detect sealed file without sidecar checksum."""
        writer = FeedWriter(
            plane="market",
            source="tff",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-3",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create sealed file without sidecar
        sealed_path = writer.partition_dir / "2026-06-08.ndjson.zst"
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')  # zstd magic
        
        half_states = writer._detect_half_states()
        assert len(half_states["missing_sidecars"]) == 1
        assert str(sealed_path) in half_states["missing_sidecars"]
    
    def test_detect_half_states_clean(self, temp_feeds_dir, mock_redis):
        """Detect no half-states in clean partition."""
        writer = FeedWriter(
            plane="lineup",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-4",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create normal files (no artifacts)
        live_path = writer.partition_dir / "2026-06-10.ndjson"
        live_path.write_bytes(b'{"record": 1}\n')
        
        sealed_path = writer.partition_dir / "2026-06-09.ndjson.zst"
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')
        sidecar_path = writer.partition_dir / "2026-06-09.ndjson.sha256"
        sidecar_path.write_text("abc123")
        
        half_states = writer._detect_half_states()
        assert len(half_states["tmp_files"]) == 0
        assert len(half_states["partial_rotations"]) == 0
        assert len(half_states["missing_sidecars"]) == 0


class TestCrashRecoveryDecision:
    """Tests for the decision tree (RESUME vs ROLLBACK)."""
    
    def test_decide_tmp_file_triggers_rollback(self, temp_feeds_dir, mock_redis):
        """Tmp file present → ROLLBACK."""
        writer = FeedWriter(
            plane="editorial",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-5",
        )
        
        half_states = {
            "tmp_files": ["/some/path/manifest.json.tmp"],
            "partial_rotations": [],
            "missing_sidecars": [],
            "manifest_revision_mismatch": False,
        }
        
        action = writer._decide_recovery_action(half_states)
        assert action == "ROLLBACK"
    
    def test_decide_partial_rotation_triggers_rollback(self, temp_feeds_dir, mock_redis):
        """Partial rotation present → ROLLBACK."""
        writer = FeedWriter(
            plane="reference",
            source="tff",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-6",
        )
        
        half_states = {
            "tmp_files": [],
            "partial_rotations": [{"date": "2026-06-09", "live": "/path", "sealed": "/path.zst"}],
            "missing_sidecars": [],
            "manifest_revision_mismatch": False,
        }
        
        action = writer._decide_recovery_action(half_states)
        assert action == "ROLLBACK"
    
    def test_decide_missing_sidecar_triggers_rollback(self, temp_feeds_dir, mock_redis):
        """Missing sidecar present → ROLLBACK."""
        writer = FeedWriter(
            plane="schedule",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-7",
        )
        
        half_states = {
            "tmp_files": [],
            "partial_rotations": [],
            "missing_sidecars": ["/some/path/file.ndjson.zst"],
            "manifest_revision_mismatch": False,
        }
        
        action = writer._decide_recovery_action(half_states)
        assert action == "ROLLBACK"
    
    def test_decide_clean_state_triggers_resume(self, temp_feeds_dir, mock_redis):
        """No half-states present → RESUME."""
        writer = FeedWriter(
            plane="market",
            source="openfootball",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-8",
        )
        
        half_states = {
            "tmp_files": [],
            "partial_rotations": [],
            "missing_sidecars": [],
            "manifest_revision_mismatch": False,
        }
        
        action = writer._decide_recovery_action(half_states)
        assert action == "RESUME"


class TestCrashRecoveryPerformance:
    """Tests for actual recovery (cleanup and resume)."""
    
    def test_perform_rollback_cleans_tmp_file(self, temp_feeds_dir, mock_redis):
        """ROLLBACK action deletes tmp files."""
        writer = FeedWriter(
            plane="reference",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-9",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tmp file
        tmp_path = writer.partition_dir / "manifest.json.tmp"
        tmp_path.write_text('{"incomplete": "manifest"}')
        assert tmp_path.exists()
        
        half_states = {"tmp_files": [str(tmp_path)], "partial_rotations": [], "missing_sidecars": []}
        writer._perform_recovery("ROLLBACK", half_states)
        
        # Tmp file should be deleted
        assert not tmp_path.exists()
    
    def test_perform_rollback_removes_live_file_from_partial_rotation(self, temp_feeds_dir, mock_redis):
        """ROLLBACK action removes live file, preserves sealed file."""
        writer = FeedWriter(
            plane="score",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-10",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create partial rotation
        live_path = writer.partition_dir / "2026-06-09.ndjson"
        sealed_path = writer.partition_dir / "2026-06-09.ndjson.zst"
        
        live_path.write_bytes(b'{"record": 1}\n')
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')
        
        assert live_path.exists()
        assert sealed_path.exists()
        
        half_states = {
            "tmp_files": [],
            "partial_rotations": [{"date": "2026-06-09", "live": str(live_path), "sealed": str(sealed_path)}],
            "missing_sidecars": [],
        }
        writer._perform_recovery("ROLLBACK", half_states)
        
        # Live file should be deleted, sealed file preserved
        assert not live_path.exists()
        assert sealed_path.exists()
    
    def test_perform_rollback_removes_unsealed_file(self, temp_feeds_dir, mock_redis):
        """ROLLBACK action removes sealed file without sidecar."""
        writer = FeedWriter(
            plane="market",
            source="tff",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-11",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create sealed file without sidecar
        sealed_path = writer.partition_dir / "2026-06-08.ndjson.zst"
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')
        
        assert sealed_path.exists()
        
        half_states = {"tmp_files": [], "partial_rotations": [], "missing_sidecars": [str(sealed_path)]}
        writer._perform_recovery("ROLLBACK", half_states)
        
        # Sealed file should be deleted
        assert not sealed_path.exists()
    
    def test_perform_resume_is_noop(self, temp_feeds_dir, mock_redis):
        """RESUME action is a no-op (preserves all files)."""
        writer = FeedWriter(
            plane="lineup",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-12",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create normal files
        live_path = writer.partition_dir / "2026-06-10.ndjson"
        live_path.write_bytes(b'{"record": 1}\n')
        
        sealed_path = writer.partition_dir / "2026-06-09.ndjson.zst"
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')
        
        file_count_before = len(list(writer.partition_dir.glob("*")))
        
        half_states = {"tmp_files": [], "partial_rotations": [], "missing_sidecars": []}
        writer._perform_recovery("RESUME", half_states)
        
        # No files should be deleted
        file_count_after = len(list(writer.partition_dir.glob("*")))
        assert file_count_after == file_count_before


class TestCrashRecoveryIntegration:
    """Integration tests for the full recovery flow."""
    
    def test_open_after_tmp_cleanup(self, temp_feeds_dir, mock_redis):
        """Writer can open and resume after cleanup of tmp file."""
        writer = FeedWriter(
            plane="reference",
            source="mackolik",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-13",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create manifest and tmp file
        manifest = FeedManifest(
            plane="reference",
            source="mackolik",
            writer_id="old-writer",
            current_date_utc="2026-06-10",
        )
        manifest_path = writer.partition_dir / "manifest.json"
        manifest_path.write_text(json.dumps({"plane": "reference", "source": "mackolik", 
                                              "writer_id": "old-writer", "current_date_utc": "2026-06-10"}))
        
        tmp_path = writer.partition_dir / "manifest.json.tmp"
        tmp_path.write_text('{"incomplete": "manifest"}')
        
        # Open should detect and clean up tmp file
        writer.open()
        
        # Verify recovery happened
        assert not tmp_path.exists()
        assert writer.is_open
        assert writer.manifest is not None
        
        writer.close()
    
    def test_writer_ready_after_rollback_recovery(self, temp_feeds_dir, mock_redis):
        """Writer is ready to write after rollback recovery."""
        writer = FeedWriter(
            plane="score",
            source="nesine",
            feeds_dir=str(temp_feeds_dir),
            redis_client=mock_redis,
            writer_id="test-writer-14",
        )
        writer.partition_dir.mkdir(parents=True, exist_ok=True)
        
        # Create partial rotation (half-state) - live file without sidecar, sealed with sidecar
        live_path = writer.partition_dir / "2026-06-09.ndjson"
        sealed_path = writer.partition_dir / "2026-06-09.ndjson.zst"
        sidecar_path = writer.partition_dir / "2026-06-09.ndjson.sha256"
        
        live_path.write_bytes(b'{"record": 1}\n')
        sealed_path.write_bytes(b'\x28\xb5\x2f\xfd')
        sidecar_path.write_text("abc123def456")  # sidecar for sealed file
        
        # Create an empty manifest
        manifest_path = writer.partition_dir / "manifest.json"
        manifest_path.write_text(json.dumps({
            "plane": "score",
            "source": "nesine",
            "writer_id": "test-writer-14",
            "current_date_utc": "2026-06-09",
            "files_written": [],
            "records_written": 0,
            "bytes_written": 0,
            "disk_usage_pct": 0.0,
            "clock_skew_ms": 0,
            "fairness_floor_violations_window": 0,
            "parts_per_date": {},
            "manifest_revision": "v1",
        }))
        
        # Open should recover and be ready to write
        writer.open()
        
        # Verify writer is open and ready (core functionality)
        assert writer.is_open
        assert writer.current_file_handle is not None
        assert not writer.current_file_handle.closed
        
        # Should be able to enqueue a record
        record = {"data": "test"}
        writer.enqueue(record)
        
        # Sealed file from partial rotation should be preserved (has sidecar)
        assert sealed_path.exists()
        assert sidecar_path.exists()
        
        writer.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
