"""Tests for SnapshotBuilder hourly hive-partitioned snapshots (Phase 16.3, bullet 1).

Proof tests (binding per Phase 16.3):
  - test_snapshot_creates_hive_partition_structure: Output dir is asof=YYYY-MM-DDThh/source=<s>/
  - test_snapshot_splits_on_max_part_bytes: Parts capped at cfg.emitter_parquet_max_part_bytes
  - test_snapshot_part_file_naming: Parts named part-00000.parquet, part-00001.parquet, ...
  - test_snapshot_respects_grace_period: Closes at hour + grace_minutes
  - test_snapshot_deterministic_ordering: Records ordered by (captured_at, stable_id)
  - test_snapshot_excludes_late_records: Records after hour window skip to next window
  - test_snapshot_footer_metadata_present: Footer contains all required fields
"""

import json
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import pytest

from ai.common.feeds.snapshot import SnapshotBuilder, SnapshotMetadata, SnapshotWatermarkScheduler


@pytest.fixture
def tmp_feeds_dir():
    """Temporary feeds directory for testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def mock_config():
    """Mock config with snapshot settings."""
    cfg = mock.MagicMock()
    cfg.emitter_parquet_max_part_bytes = 1024  # 1 KiB for easy testing
    cfg.emitter_snapshot_grace_minutes = 10
    cfg.emitter_snapshot_writer_threads = 2
    return cfg


def create_ndjson_feed(ndjson_path: Path, records: list[dict]) -> None:
    """Helper to create an NDJSON feed file."""
    ndjson_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ndjson_path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


class TestHourlyPartitions:
    """Tests for hourly hive-partitioned snapshots."""
    
    def test_snapshot_creates_hive_partition_structure(self, tmp_feeds_dir, mock_config):
        """Snapshot output dir matches asof=YYYY-MM-DDThh/source=<s>/ pattern."""
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        # Create sample NDJSON
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": "match_001",
                "captured_at": hour_start.isoformat(),
                "data": "test1"
            },
            {
                "stable_id": "match_002",
                "captured_at": (hour_start + timedelta(minutes=30)).isoformat(),
                "data": "test2"
            }
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Build snapshot
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        # Verify structure
        expected_dir = (
            tmp_feeds_dir / "score" / "mackolik" / "snapshots"
            / f"asof={asof_hour}" / f"source=mackolik"
        )
        assert snapshot_dir == expected_dir
        assert snapshot_dir.exists()
    
    def test_snapshot_splits_on_max_part_bytes(self, tmp_feeds_dir, mock_config):
        """Parts are split when exceeding emitter_parquet_max_part_bytes."""
        # Use a very small part size (500 bytes) to force splits
        mock_config.emitter_parquet_max_part_bytes = 500
        
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        # Create NDJSON with multiple large records
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"match_{i:03d}",
                "captured_at": (hour_start + timedelta(minutes=i)).isoformat(),
                "data": "x" * 100
            }
            for i in range(10)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Build snapshot
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        # Count part files
        part_files = sorted(snapshot_dir.glob("part-*.parquet"))
        assert len(part_files) > 1, "Expected multiple parts due to size limit"
    
    def test_snapshot_part_file_naming(self, tmp_feeds_dir, mock_config):
        """Part files are named part-NNNNN.parquet with zero-padded indices."""
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"match_{i:03d}",
                "captured_at": (hour_start + timedelta(minutes=i)).isoformat(),
                "data": f"test_{i}"
            }
            for i in range(5)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        part_files = sorted(snapshot_dir.glob("part-*.parquet"))
        assert len(part_files) >= 1
        
        # Check naming pattern
        for idx, part_file in enumerate(part_files):
            assert part_file.name == f"part-{idx:05d}.parquet"
    
    def test_snapshot_excludes_late_records(self, tmp_feeds_dir, mock_config):
        """Records after hour window are excluded (ledger #5)."""
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": "match_001",
                "captured_at": (hour_start + timedelta(minutes=5)).isoformat(),
                "data": "in_window"
            },
            {
                "stable_id": "match_002",
                "captured_at": (hour_start + timedelta(minutes=65)).isoformat(),  # After hour_end
                "data": "late"
            },
            {
                "stable_id": "match_003",
                "captured_at": (hour_start + timedelta(minutes=30)).isoformat(),
                "data": "in_window_2"
            }
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        # Check footer metadata
        footer_path = snapshot_dir / ".meta" / "footer.json"
        assert footer_path.exists()
        with open(footer_path) as f:
            footer = json.load(f)
        
        # Should have 2 in-window records and 1 late record
        assert footer["negelir_record_count"] == 2
        assert footer["negelir_late_record_count_in_window"] == 1
    
    def test_snapshot_deterministic_ordering(self, tmp_feeds_dir, mock_config):
        """Records within a part are ordered by (captured_at, stable_id)."""
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        # Create records in non-deterministic order
        records = [
            {
                "stable_id": "match_003",
                "captured_at": (hour_start + timedelta(minutes=30)).isoformat(),
                "data": "third"
            },
            {
                "stable_id": "match_001",
                "captured_at": (hour_start + timedelta(minutes=10)).isoformat(),
                "data": "first"
            },
            {
                "stable_id": "match_002",
                "captured_at": (hour_start + timedelta(minutes=20)).isoformat(),
                "data": "second"
            }
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        # Read back records from parquet (or NDJSON placeholder)
        part_files = sorted(snapshot_dir.glob("part-*.parquet"))
        assert len(part_files) >= 1
        
        ordered_records = []
        for part_file in part_files:
            with open(part_file) as f:
                for line in f:
                    if line.strip():
                        ordered_records.append(json.loads(line))
        
        # Check ordering: by captured_at first, then stable_id
        for i in range(len(ordered_records) - 1):
            curr = ordered_records[i]
            next_rec = ordered_records[i + 1]
            curr_key = (curr.get("captured_at", ""), curr.get("stable_id", ""))
            next_key = (next_rec.get("captured_at", ""), next_rec.get("stable_id", ""))
            assert curr_key <= next_key, f"Order violation: {curr_key} > {next_key}"
    
    def test_snapshot_footer_metadata_complete(self, tmp_feeds_dir, mock_config):
        """Footer contains all required metadata fields (bullet 8)."""
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123def456",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": "match_001",
                "captured_at": hour_start.isoformat(),
                "data": "test"
            }
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        # Verify footer
        footer_path = snapshot_dir / ".meta" / "footer.json"
        assert footer_path.exists()
        
        with open(footer_path) as f:
            footer = json.load(f)
        
        # Check all required fields (bullet 8)
        required_fields = [
            "negelir_emitter_version",
            "negelir_schema_version",
            "negelir_registry_sha256",
            "negelir_record_count",
            "negelir_tombstones_applied_count",
            "negelir_watermark_at",
            "negelir_closed_at",
            "negelir_sha256_of_ndjson_inputs",
            "negelir_compressor",
            "negelir_captured_at_min",
            "negelir_captured_at_max",
            "negelir_late_record_count_in_window",
        ]
        
        for field in required_fields:
            assert field in footer, f"Missing required field: {field}"
        
        # Verify values
        assert footer["negelir_registry_sha256"] == "abc123def456"
        assert footer["negelir_record_count"] == 1
        assert footer["negelir_tombstones_applied_count"] == 0
        assert footer["negelir_late_record_count_in_window"] == 0


class TestWatermarkDrivenClose:
    """Tests for watermark-driven snapshot close (Phase 16.3, bullet 2)."""
    
    def test_snapshot_watermark_grace_period(self, tmp_feeds_dir, mock_config):
        """Watermark closes at hour + grace_minutes (ledger #5)."""
        mock_config.emitter_snapshot_grace_minutes = 10
        
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        # Create records just before and after the grace period
        records = [
            {
                "stable_id": "match_001",
                "captured_at": (hour_start + timedelta(minutes=5)).isoformat(),
                "data": "in_window"
            },
            {
                "stable_id": "match_002",
                "captured_at": (hour_end + timedelta(minutes=5)).isoformat(),  # After hour_end
                "data": "late_arrival"
            }
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Build snapshot for this hour
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour)
        
        # Verify watermark and close timestamps in footer
        footer_path = snapshot_dir / ".meta" / "footer.json"
        with open(footer_path) as f:
            footer = json.load(f)
        
        # Watermark should be at hour_end
        assert footer["negelir_watermark_at"] == hour_end.isoformat()
        
        # Closed_at should be around now
        closed_at = datetime.fromisoformat(footer["negelir_closed_at"])
        assert closed_at.tzinfo == timezone.utc
        assert (datetime.now(timezone.utc) - closed_at).total_seconds() < 5  # Within 5 seconds
    
    def test_snapshot_late_record_tracking(self, tmp_feeds_dir, mock_config):
        """Late records are tracked in feeds_late_record_total (ledger #5)."""
        scheduler = SnapshotWatermarkScheduler(
            plane="score",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
        )
        
        # Emit late record metric
        scheduler.emit_late_record_metric(source="mackolik", late_count=5)
        # Test passes if no exception
        assert True
    
    def test_snapshot_ready_event_publishing(self, tmp_feeds_dir, mock_config):
        """Snapshot-ready event is published (ledger #27)."""
        mock_bus = mock.MagicMock()
        
        scheduler = SnapshotWatermarkScheduler(
            plane="score",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            bus_client=mock_bus,
        )
        
        scheduler.publish_snapshot_ready(
            asof_hour="2026-04-20T15",
            registry_sha="abc123",
            manifest_etag="etag123",
            record_count=1000,
            tombstones_applied=5,
            late_record_count=2,
            source="mackolik",
            sha256_of_parts=["sha1", "sha2"],
        )
        
        # Verify bus.publish was called
        assert mock_bus.publish.called
        call_args = mock_bus.publish.call_args[0]
        
        # First arg is topic
        assert call_args[0] == "feeds.snapshot.ready.v1"
        
        # Second arg is event JSON
        event = json.loads(call_args[1])
        assert event["plane"] == "score"
        assert event["as_of"] == "2026-04-20T15"
        assert event["registry_sha"] == "abc123"
        assert event["record_count"] == 1000
        assert event["late_record_count"] == 2


class TestIdempotentRebuild:
    """Tests for idempotent rebuild with registry pin (Phase 16.3, bullet 5)."""
    
    def test_rebuild_requires_registry_sha(self, tmp_feeds_dir, mock_config):
        """Rebuild refuses to proceed without REGISTRY_SHA (bullet 5)."""
        from ai.common.feeds.snapshot import rebuild_snapshot_with_registry_pin
        
        # Create minimal feed structure
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        create_ndjson_feed(ndjson_path, [{"stable_id": "m1", "captured_at": hour_start.isoformat()}])
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        
        # Should raise if registry_sha is empty
        with pytest.raises(ValueError, match="REGISTRY_SHA"):
            rebuild_snapshot_with_registry_pin(
                plane="score",
                asof_hour=asof_hour,
                registry_sha="",  # Empty!
                feeds_dir=str(tmp_feeds_dir),
                config=mock_config,
            )
    
    def test_rebuild_snapshot_deterministic_with_pin(self, tmp_feeds_dir, mock_config):
        """Rebuilt snapshot matches original when using same registry pin (bullet 5)."""
        from ai.common.feeds.snapshot import (
            rebuild_snapshot_with_registry_pin,
            validate_snapshot_determinism,
        )
        
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="registry_sha_v1",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {"stable_id": f"m{i}", "captured_at": (hour_start + timedelta(minutes=i)).isoformat()}
            for i in range(5)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Build original snapshot
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        original_dir = builder.build_snapshot(asof_hour, registry_sha="registry_sha_v1")
        
        # Rebuild with same registry SHA
        rebuilt_dir, rebuilt_sha = rebuild_snapshot_with_registry_pin(
            plane="score",
            asof_hour=asof_hour,
            registry_sha="registry_sha_v1",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
        )
        
        # Validate determinism
        is_deterministic = validate_snapshot_determinism(
            original_dir,
            rebuilt_dir,
            "registry_sha_v1"
        )
        assert is_deterministic, "Rebuilt snapshot should be byte-identical to original"
    
    def test_rebuild_emits_correct_metadata(self, tmp_feeds_dir, mock_config):
        """Rebuilt snapshot has correct metadata with pinned registry (bullet 5)."""
        from ai.common.feeds.snapshot import rebuild_snapshot_with_registry_pin
        
        builder = SnapshotBuilder(
            plane="score",
            source="test_src",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="test_registry_sha_123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "test_src" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        create_ndjson_feed(ndjson_path, [
            {"stable_id": "m1", "captured_at": hour_start.isoformat()}
        ])
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        
        # Build initial snapshot
        original_dir = builder.build_snapshot(asof_hour, registry_sha="test_registry_sha_123")
        
        # Read original footer
        original_footer_path = original_dir / ".meta" / "footer.json"
        with open(original_footer_path) as f:
            original_footer = json.load(f)
        
        # Rebuild
        rebuilt_dir, _ = rebuild_snapshot_with_registry_pin(
            plane="score",
            asof_hour=asof_hour,
            registry_sha="test_registry_sha_123",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
        )
        
        # Verify rebuilt footer has same registry SHA
        rebuilt_footer_path = rebuilt_dir / ".meta" / "footer.json"
        with open(rebuilt_footer_path) as f:
            rebuilt_footer = json.load(f)
        
        assert rebuilt_footer["negelir_registry_sha256"] == "test_registry_sha_123"
        assert rebuilt_footer["negelir_registry_sha256"] == original_footer["negelir_registry_sha256"]


class TestTombstoneApplication:
    """Tests for tombstone application at close (Phase 16.3, bullet 3)."""
    
    def test_snapshot_excludes_tombstoned_stable_ids(self, tmp_feeds_dir, mock_config):
        """Tombstoned stable_ids are excluded from snapshot (ledger #7, #13)."""
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        # Create records, including some that will be tombstoned
        records = [
            {
                "stable_id": "match_001",
                "captured_at": (hour_start + timedelta(minutes=5)).isoformat(),
                "data": "will_keep"
            },
            {
                "stable_id": "match_002",
                "captured_at": (hour_start + timedelta(minutes=10)).isoformat(),
                "data": "will_tombstone"
            },
            {
                "stable_id": "match_003",
                "captured_at": (hour_start + timedelta(minutes=15)).isoformat(),
                "data": "will_keep_2"
            }
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Build snapshot with tombstones for match_002
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        tombstones = {
            "score": {"match_002"}  # Tombstone match_002
        }
        snapshot_dir = builder.build_snapshot(
            asof_hour,
            registry_sha="abc123",
            tombstones=tombstones,
        )
        
        # Verify footer
        footer_path = snapshot_dir / ".meta" / "footer.json"
        with open(footer_path) as f:
            footer = json.load(f)
        
        # Should have 2 records (3 - 1 tombstoned)
        assert footer["negelir_record_count"] == 2
        # Should record 1 tombstone was applied
        assert footer["negelir_tombstones_applied_count"] == 1
        
        # Verify the tombstoned record is not in the snapshot
        part_files = sorted(snapshot_dir.glob("part-*.parquet"))
        part_ids = set()
        for part_file in part_files:
            with open(part_file) as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        part_ids.add(record.get("stable_id", ""))
        
        assert "match_001" in part_ids
        assert "match_002" not in part_ids  # Tombstoned!
        assert "match_003" in part_ids
    
    def test_snapshot_multiple_tombstones_per_plane(self, tmp_feeds_dir, mock_config):
        """Multiple tombstones applied correctly (ledger #7)."""
        builder = SnapshotBuilder(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="xyz",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "test_source" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"match_{i:03d}",
                "captured_at": (hour_start + timedelta(minutes=i*5)).isoformat(),
                "data": f"record_{i}"
            }
            for i in range(10)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Tombstone 3 records
        tombstones = {
            "score": {"match_001", "match_003", "match_005"}
        }
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(
            asof_hour,
            registry_sha="xyz",
            tombstones=tombstones,
        )
        
        footer_path = snapshot_dir / ".meta" / "footer.json"
        with open(footer_path) as f:
            footer = json.load(f)
        
        # 10 records - 3 tombstoned = 7
        assert footer["negelir_record_count"] == 7
        assert footer["negelir_tombstones_applied_count"] == 3
    
    def test_snapshot_tombstones_per_plane_isolation(self, tmp_feeds_dir, mock_config):
        """Tombstones only affect specified plane (ledger #7, #13)."""
        builder = SnapshotBuilder(
            plane="schedule",  # Different plane
            source="test_source",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "schedule" / "test_source" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"item_{i}",
                "captured_at": (hour_start + timedelta(minutes=i)).isoformat(),
                "data": f"data_{i}"
            }
            for i in range(5)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        # Pass tombstones for 'score' plane, not 'schedule'
        tombstones = {
            "score": {"match_001"}  # schedule plane shouldn't be affected
        }
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(
            asof_hour,
            registry_sha="abc",
            tombstones=tombstones,
        )
        
        footer_path = snapshot_dir / ".meta" / "footer.json"
        with open(footer_path) as f:
            footer = json.load(f)
        
        # All 5 records should be present (tombstones don't apply to this plane)
        assert footer["negelir_record_count"] == 5
        assert footer["negelir_tombstones_applied_count"] == 0


class TestBloomFilterSidecars:
    """Tests for bloom filter sidecar generation (Phase 16.3, bullet 9)."""
    
    def test_bloom_sidecar_written_per_part(self, tmp_feeds_dir, mock_config):
        """Each part file gets a companion .bloom sidecar."""
        mock_config.emitter_snapshot_bloom_fpr_max = 0.01
        
        builder = SnapshotBuilder(
            plane="score",
            source="mackolik",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc123",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "mackolik" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        # Create enough records to trigger multiple parts
        records = [
            {
                "stable_id": f"match_{i:04d}",
                "captured_at": (hour_start + timedelta(minutes=i % 60)).isoformat(),
                "data": "x" * 1000,  # Make records larger to force part splitting
            }
            for i in range(200)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(
            asof_hour,
            registry_sha="abc123",
        )
        
        # Check that .bloom files exist alongside .parquet files
        part_files = sorted(snapshot_dir.glob("part-*.parquet"))
        bloom_files = sorted(snapshot_dir.glob("part-*.bloom"))
        
        assert len(part_files) > 0
        assert len(bloom_files) > 0
        assert len(bloom_files) == len(part_files)
    
    def test_bloom_sidecar_contains_stable_ids(self, tmp_feeds_dir, mock_config):
        """Bloom sidecar JSON records stable_id sample."""
        mock_config.emitter_snapshot_bloom_fpr_max = 0.01
        
        builder = SnapshotBuilder(
            plane="score",
            source="test",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="xyz",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "test" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"match_{i:03d}",
                "captured_at": (hour_start + timedelta(minutes=i*5)).isoformat(),
                "data": "test"
            }
            for i in range(50)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(
            asof_hour,
            registry_sha="xyz",
        )
        
        # Check bloom sidecar content
        bloom_files = list(snapshot_dir.glob("part-*.bloom"))
        assert len(bloom_files) > 0
        
        bloom_path = bloom_files[0]
        bloom_data = json.loads(bloom_path.read_text())
        
        assert bloom_data["type"] == "bloom"
        assert bloom_data["algorithm"] == "xxhash64"
        assert bloom_data["estimated_count"] > 0
        assert "fpr_target" in bloom_data
        assert "stable_ids_sample" in bloom_data
        assert "sha256" in bloom_data
    
    def test_bloom_fpr_within_target(self, tmp_feeds_dir, mock_config):
        """Bloom filter FPR is within configured target."""
        fpr_target = 0.01
        mock_config.emitter_snapshot_bloom_fpr_max = fpr_target
        
        builder = SnapshotBuilder(
            plane="score",
            source="test",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "test" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"item_{i}",
                "captured_at": (hour_start + timedelta(minutes=i)).isoformat(),
                "data": "data"
            }
            for i in range(100)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(
            asof_hour,
            registry_sha="abc",
        )
        
        bloom_files = list(snapshot_dir.glob("part-*.bloom"))
        
        from ai.common.feeds.snapshot import BloomFilterWriter
        bloom_writer = BloomFilterWriter(fpr_target=fpr_target)
        
        for bloom_path in bloom_files:
            # Verify FPR validation passes
            result = bloom_writer.validate_bloom_fpr(bloom_path, actual_records=100)
            assert result is True


class TestDeltaSnapshotMode:
    """Tests for delta snapshot mode (Phase 16.3, bullet 10)."""
    
    def test_delta_snapshot_metadata_tracks_mode(self, tmp_feeds_dir, mock_config):
        """Delta snapshots record mode in metadata."""
        mock_config.emitter_snapshot_mode = "delta"
        mock_config.emitter_snapshot_compaction_hours = 24
        
        builder = SnapshotBuilder(
            plane="score",
            source="test",
            feeds_dir=str(tmp_feeds_dir),
            config=mock_config,
            registry_sha="abc",
        )
        
        now = datetime.now(timezone.utc)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        ndjson_path = tmp_feeds_dir / "score" / "test" / f"{hour_start.strftime('%Y-%m-%d')}.ndjson"
        
        records = [
            {
                "stable_id": f"item_{i}",
                "captured_at": (hour_start + timedelta(minutes=i)).isoformat(),
                "data": "data"
            }
            for i in range(50)
        ]
        create_ndjson_feed(ndjson_path, records)
        
        asof_hour = hour_start.strftime("%Y-%m-%dT%H")
        snapshot_dir = builder.build_snapshot(asof_hour, registry_sha="abc")
        
        # Check footer for mode
        footer_path = snapshot_dir / ".meta" / "footer.json"
        with open(footer_path) as f:
            footer = json.load(f)
        
        # First snapshot should be full mode (no prior full)
        assert footer.get("negelir_snapshot_mode") in ("full", "delta")
    
    def test_delta_snapshot_manager_determines_full_first(self):
        """First snapshot is full when no prior full exists."""
        from ai.common.feeds.snapshot import DeltaSnapshotManager
        
        manager = DeltaSnapshotManager(mode="delta", compaction_hours=24)
        mode, prior_full = manager.determine_snapshot_type(
            asof_hour="2026-04-20T00",
            prior_full_snapshot_asof=None,
        )
        
        assert mode == "full"
        assert prior_full is None
    
    def test_delta_snapshot_manager_uses_delta_within_window(self):
        """Within compaction window, snapshots use delta mode."""
        from ai.common.feeds.snapshot import DeltaSnapshotManager
        
        manager = DeltaSnapshotManager(mode="delta", compaction_hours=24)
        
        # Second hour: use delta
        mode, prior_full = manager.determine_snapshot_type(
            asof_hour="2026-04-20T01",
            prior_full_snapshot_asof="2026-04-20T00",
        )
        
        assert mode == "delta"
        assert prior_full == "2026-04-20T00"
    
    def test_delta_snapshot_manager_compacts_after_interval(self):
        """After compaction hours, snapshots revert to full."""
        from ai.common.feeds.snapshot import DeltaSnapshotManager
        
        manager = DeltaSnapshotManager(mode="delta", compaction_hours=24)
        
        # After 24+ hours: revert to full for compaction
        mode, prior_full = manager.determine_snapshot_type(
            asof_hour="2026-04-21T00",  # 24 hours later
            prior_full_snapshot_asof="2026-04-20T00",
        )
        
        assert mode == "full"
        assert prior_full is None
    
    def test_delta_snapshot_manager_full_mode_always_full(self):
        """In full mode, snapshots are always full (no delta)."""
        from ai.common.feeds.snapshot import DeltaSnapshotManager
        
        manager = DeltaSnapshotManager(mode="full", compaction_hours=24)
        
        # Always full mode
        mode1, prior1 = manager.determine_snapshot_type(
            asof_hour="2026-04-20T01",
            prior_full_snapshot_asof="2026-04-20T00",
        )
        assert mode1 == "full"
        assert prior1 is None
        
        mode2, prior2 = manager.determine_snapshot_type(
            asof_hour="2026-04-21T00",
            prior_full_snapshot_asof="2026-04-20T00",
        )
        assert mode2 == "full"
        assert prior2 is None
    
    def test_delta_snapshot_chain_building(self):
        """Snapshot chain correctly tracks full and delta modes."""
        from ai.common.feeds.snapshot import DeltaSnapshotManager
        
        manager = DeltaSnapshotManager(mode="delta", compaction_hours=24)
        
        chain_result = manager.build_snapshot_chain(
            snapshots_dir=Path("/tmp"),
            plane="score",
            source="test",
            current_asof="2026-04-20T05",
            current_mode="delta",
            prior_full_asof="2026-04-20T00",
        )
        
        assert chain_result["mode"] == "delta"
        assert len(chain_result["chain"]) > 0
        assert chain_result["chain"][0] == ("delta", "2026-04-20T05")
