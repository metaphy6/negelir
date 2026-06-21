"""Phase 16.29 proof test: PITR replay reconstructs manifest accurately."""
import json
import tempfile
import datetime
from pathlib import Path

from common.feeds.changelog import ManifestChangelog, replay_changelog_to_target


def test_pitr_replay_reconstructs_manifest():
    """Test that replaying changelog from snapshot returns a valid manifest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create initial manifest
        initial_manifest = {
            "version": "1.0.0",
            "planes": {"score": {"version": 1}, "reference": {"version": 1}},
        }
        
        # Create changelog and snapshot
        now = datetime.datetime(2026, 6, 12, 15, 30, 0, tzinfo=datetime.timezone.utc)
        changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now)
        changelog.snapshot_manifest("snap_v1", initial_manifest)
        
        # Record mutations
        changelog.append(
            manifest_revision="v2",
            mutation={"kind": "add_plane", "plane": "lineup"},
            sha256_after="hash_v2",
        )
        
        changelog.append(
            manifest_revision="v3",
            mutation={"kind": "update_plane", "plane": "score"},
            sha256_after="hash_v3",
        )
        
        changelog.close()
        
        # Replay to the target time (after all mutations)
        target_time = "2026-06-12T15:31:00Z"
        replayed = replay_changelog_to_target(
            feeds_root=tmpdir,
            region="eu",
            target_time_utc=target_time,
            base_snapshot_revision=None,
        )
        
        # Verify we got a valid manifest from the snapshot
        assert isinstance(replayed, dict)
        assert replayed["version"] == "1.0.0"
        assert "score" in replayed["planes"]
        assert "reference" in replayed["planes"]


def test_pitr_to_arbitrary_second_within_retention():
    """Test that PITR can restore to any second within retention window."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        manifest = {"version": "1.0", "planes": {"test": {}}}
        now = datetime.datetime(2026, 6, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
        changelog = ManifestChangelog(feeds_root=tmpdir, region="eu", now_fn=lambda: now)
        changelog.snapshot_manifest("snap", manifest)
        
        # Add mutations at different times
        for minute in range(0, 5):
            ts = now + datetime.timedelta(minutes=minute)
            changelog.now_fn = lambda ts=ts: ts
            changelog.append(
                manifest_revision=f"v{minute}",
                mutation={"kind": "test", "minute": minute},
                sha256_after=f"hash_{minute}",
            )
        
        changelog.close()
        
        # Try to restore at various times within the retention window
        for target_minute in [0, 1, 2, 3, 4]:
            target_time = (now + datetime.timedelta(minutes=target_minute)).strftime("%Y-%m-%dT%H:%M:%SZ")
            result = replay_changelog_to_target(
                feeds_root=tmpdir,
                region="eu",
                target_time_utc=target_time,
                base_snapshot_revision=None,
            )
            # Should return a valid manifest
            assert isinstance(result, dict)
            assert result["version"] == "1.0"
