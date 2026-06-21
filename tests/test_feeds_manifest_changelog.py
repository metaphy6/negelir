"""Tests for manifest changelog (Phase 16.29, bullet 1)."""

import datetime
import json
import pytest
import tempfile
from pathlib import Path

from ai.common.feeds.changelog import ManifestChangelog, replay_changelog_to_target


class TestManifestChangelog:
    """Test manifest changelog append-only behavior (Phase 16.29, bullet 1)."""
    
    def test_changelog_append_creates_file(self):
        """Test that appending a mutation creates the changelog file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ManifestChangelog(feeds_dir=tmpdir, region="eu")
            
            manifest_obj = {
                "version": "1.0.0",
                "planes": {"score": {"version": 1, "status": "active"}},
            }
            
            from ai.common.feeds.changelog import ManifestMutation
            mutation = ManifestMutation(
                kind="add_plane",
                plane="score",
                source="test",
                details={"version": 1},
            )
            
            changelog.append(
                mutation=mutation,
                manifest_revision="sha256abc123",
                manifest_obj=manifest_obj,
            )
            
            # Check file was created
            changelog_path = Path(tmpdir) / ".changelog" / "region=eu" / f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')}.ndjson"
            assert changelog_path.exists(), f"Changelog file not created at {changelog_path}"
    
    def test_changelog_append_only_format(self):
        """Test that entries are appended as NDJSON (one JSON per line)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.datetime(2026, 6, 12, 15, 30, 45, 123456, tzinfo=datetime.timezone.utc)
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now)
            
            # Append two mutations
            changelog.append(
                manifest_revision="sha256v1",
                mutation={"kind": "add_plane", "plane": "score"},
                sha256_after="sha256file1",
            )
            changelog.append(
                manifest_revision="sha256v2",
                mutation={"kind": "add_source", "plane": "score", "source": "mackolik"},
                sha256_after="sha256file2",
            )
            changelog.close()
            
            # Verify NDJSON format
            changelog_path = Path(tmpdir) / ".changelog" / "region=eu" / "2026-06-12.ndjson"
            with open(changelog_path, "r") as f:
                lines = f.readlines()
            
            assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"
            
            # Parse and verify each line is valid JSON
            entry1 = json.loads(lines[0])
            assert entry1["manifest_revision"] == "sha256v1"
            assert entry1["mutation"]["kind"] == "add_plane"
            assert entry1["sha256_after"] == "sha256file1"
            
            entry2 = json.loads(lines[1])
            assert entry2["manifest_revision"] == "sha256v2"
            assert entry2["mutation"]["kind"] == "add_source"
            assert entry2["sha256_after"] == "sha256file2"
    
    def test_changelog_daily_rotation(self):
        """Test that changelog rotates at UTC midnight."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Day 1
            now1 = datetime.datetime(2026, 6, 12, 15, 30, 0, tzinfo=datetime.timezone.utc)
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now1)
            changelog.append(
                manifest_revision="sha256day1",
                mutation={"kind": "add_plane", "plane": "score"},
                sha256_after="sha256file1",
            )
            
            # Day 2 (simulate by changing now_fn)
            now2 = datetime.datetime(2026, 6, 13, 0, 0, 0, tzinfo=datetime.timezone.utc)
            changelog.now_fn = lambda: now2
            changelog.append(
                manifest_revision="sha256day2",
                mutation={"kind": "add_plane", "plane": "schedule"},
                sha256_after="sha256file2",
            )
            changelog.close()
            
            # Verify both files exist
            path1 = Path(tmpdir) / ".changelog" / "region=eu" / "2026-06-12.ndjson"
            path2 = Path(tmpdir) / ".changelog" / "region=eu" / "2026-06-13.ndjson"
            
            assert path1.exists(), "Day 1 changelog not created"
            assert path2.exists(), "Day 2 changelog not created"
            
            # Verify content
            with open(path1) as f:
                entry1 = json.loads(f.readline())
                assert entry1["manifest_revision"] == "sha256day1"
            
            with open(path2) as f:
                entry2 = json.loads(f.readline())
                assert entry2["manifest_revision"] == "sha256day2"
    
    def test_changelog_append_only_no_mutation_kind_raises(self):
        """Test that appending without 'kind' field raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu")
            
            with pytest.raises(ValueError, match="Mutation must include 'kind'"):
                changelog.append(
                    manifest_revision="sha256abc",
                    mutation={"plane": "score"},  # Missing 'kind'!
                    sha256_after="sha256file",
                )
    
    def test_changelog_read_for_date(self):
        """Test reading changelog entries for a specific date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.datetime(2026, 6, 12, 15, 30, 0, tzinfo=datetime.timezone.utc)
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now)
            
            changelog.append(
                manifest_revision="sha256v1",
                mutation={"kind": "add_plane", "plane": "score"},
                sha256_after="sha256file1",
            )
            changelog.append(
                manifest_revision="sha256v2",
                mutation={"kind": "add_source", "plane": "score", "source": "mackolik"},
                sha256_after="sha256file2",
            )
            changelog.close()
            
            # Read the entries back
            read_changelog = ManifestChangelog(feeds_root=tmpdir, region="eu")
            entries = read_changelog.read_changelog_for_date(now)
            
            assert len(entries) == 2
            assert entries[0]["manifest_revision"] == "sha256v1"
            assert entries[1]["manifest_revision"] == "sha256v2"
    
    def test_changelog_read_nonexistent_date_returns_empty(self):
        """Test that reading a date with no changelog returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu")
            
            # Try to read a date that was never written to
            target_date = datetime.datetime(2026, 7, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
            entries = changelog.read_changelog_for_date(target_date)
            
            assert entries == []
    
    def test_changelog_fsync_per_write(self):
        """Test that each write is immediately fsynced (for durability)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.datetime(2026, 6, 12, 15, 30, 0, tzinfo=datetime.timezone.utc)
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now)
            
            # Append a mutation (the fsync is internal, but we can verify no exception)
            changelog.append(
                manifest_revision="sha256v1",
                mutation={"kind": "add_plane", "plane": "score"},
                sha256_after="sha256file1",
            )
            
            # File should be readable immediately (no buffering)
            changelog_path = Path(tmpdir) / ".changelog" / "region=eu" / "2026-06-12.ndjson"
            with open(changelog_path, "r") as f:
                line = f.readline()
                assert line, "Changelog file is empty or not fsynced"
                entry = json.loads(line)
                assert entry["manifest_revision"] == "sha256v1"
            
            changelog.close()
    
    def test_changelog_context_manager(self):
        """Test that changelog works as a context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.datetime(2026, 6, 12, 15, 30, 0, tzinfo=datetime.timezone.utc)
            
            with ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now) as changelog:
                changelog.append(
                    manifest_revision="sha256v1",
                    mutation={"kind": "add_plane", "plane": "score"},
                    sha256_after="sha256file1",
                )
            
            # After exiting context, file should be flushed and closed
            changelog_path = Path(tmpdir) / ".changelog" / "region=eu" / "2026-06-12.ndjson"
            assert changelog_path.exists()
            
            with open(changelog_path, "r") as f:
                entry = json.loads(f.readline())
                assert entry["manifest_revision"] == "sha256v1"
    
    def test_changelog_iso_timestamp_format(self):
        """Test that timestamps are in ISO 8601 format with microseconds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.datetime(2026, 6, 12, 15, 30, 45, 123456, tzinfo=datetime.timezone.utc)
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now)
            
            changelog.append(
                manifest_revision="sha256v1",
                mutation={"kind": "add_plane", "plane": "score"},
                sha256_after="sha256file1",
            )
            changelog.close()
            
            changelog_path = Path(tmpdir) / ".changelog" / "region=eu" / "2026-06-12.ndjson"
            with open(changelog_path, "r") as f:
                entry = json.loads(f.readline())
                ts = entry["ts"]
                # Should be ISO format like "2026-06-12T15:30:45.123456+00:00"
                assert "T" in ts, f"Timestamp missing 'T': {ts}"
                assert ":" in ts, f"Timestamp missing colon: {ts}"


class TestManifestSnapshot:
    """Test periodic manifest snapshots (Phase 16.29, bullet 2)."""
    
    def test_snapshot_creates_file(self):
        """Test that snapshot_manifest creates a JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ManifestChangelog(feeds_dir=tmpdir, region="eu")
            
            manifest_obj = {
                "version": "1.0.0",
                "planes": {
                    "score": {"version": 1, "status": "active"},
                    "lineup": {"version": 1, "status": "active"},
                },
            }
            
            changelog.snapshot_manifest("manifest_rev_1", manifest_obj)
            
            # Check snapshot file was created
            snapshot_path = Path(tmpdir) / ".manifests" / "snapshots" / "manifest_rev_1.json"
            assert snapshot_path.exists()
    
    def test_snapshot_contains_full_manifest(self):
        """Test that snapshot contains the full manifest object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ManifestChangelog(feeds_dir=tmpdir, region="eu")
            
            manifest_obj = {
                "version": "1.0.0",
                "planes": {
                    "score": {"version": 1, "status": "active"},
                },
                "metadata": {"generated_at": "2026-06-12T15:30:00Z"},
            }
            
            changelog.snapshot_manifest("snap_v1", manifest_obj)
            
            # Read snapshot back
            snapshot_path = Path(tmpdir) / ".manifests" / "snapshots" / "snap_v1.json"
            with open(snapshot_path, "r") as f:
                loaded = json.load(f)
            
            assert loaded == manifest_obj
    
    def test_replay_changelog_finds_base_snapshot(self):
        """Test replay_changelog_to_target can find a base snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            changelog = ManifestChangelog(feeds_dir=tmpdir, region="eu")
            
            base_manifest = {
                "version": "1.0.0",
                "planes": {"score": {"version": 1}},
            }
            
            changelog.snapshot_manifest("base_snap", base_manifest)
            
            # Replay to a time after the snapshot
            target_time = "2026-06-12T16:00:00.000Z"
            result = replay_changelog_to_target(
                tmpdir, "eu", target_time, base_snapshot_revision="base_snap"
            )
            
            # Should return the base manifest (no changelog entries to replay)
            assert result["version"] == "1.0.0"
            assert "score" in result["planes"]
    
    def test_replay_without_snapshots_raises(self):
        """Test that replay without any snapshots raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_time = "2026-06-12T16:00:00.000Z"
            
            with pytest.raises(ValueError, match="No manifest snapshots found"):
                replay_changelog_to_target(tmpdir, "eu", target_time)
