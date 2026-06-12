"""Tests for FeedReader.time_travel() (Phase 16.4, bullet 1; ledger #35)."""

import datetime
import pytest
import tempfile
import json
from pathlib import Path

from common.feeds.reader import FeedReader
from common.feeds.changelog import ManifestChangelog


class TestFeedReaderTimeTravel:
    """Test time-travel reads (Phase 16.4, bullet 1)."""
    
    def test_time_travel_creates_reader(self):
        """Test that time_travel() returns a FeedReader instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a base snapshot
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu")
            base_manifest = {
                "version": "1.0.0",
                "planes": {"score": {"version": 1, "status": "active"}},
            }
            changelog.snapshot_manifest("base_snap", base_manifest)
            
            # Create a FeedReader and time-travel to a point in the past
            reader = FeedReader(
                feeds_path=tmpdir,
                verify_schema_on_init=False,
            )
            
            target_time = "2026-06-12T12:00:00Z"
            time_travel_reader = reader.time_travel(as_of=target_time)
            
            # Verify it's a FeedReader
            assert isinstance(time_travel_reader, FeedReader)
            # Verify it's marked as a time-travel reader
            assert time_travel_reader.is_time_travel_reader()
            # Verify it has the correct as_of time
            assert time_travel_reader.get_time_travel_as_of() == target_time
    
    def test_time_travel_without_snapshots_raises(self):
        """Test that time_travel() raises if no snapshots exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = FeedReader(
                feeds_path=tmpdir,
                verify_schema_on_init=False,
            )
            
            target_time = "2026-06-12T12:00:00Z"
            
            with pytest.raises(ValueError, match="No manifest snapshots found"):
                reader.time_travel(as_of=target_time)
    
    def test_is_time_travel_reader_false_for_normal_reader(self):
        """Test that normal readers are not marked as time-travel readers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = FeedReader(
                feeds_path=tmpdir,
                verify_schema_on_init=False,
            )
            
            assert not reader.is_time_travel_reader()
            assert reader.get_time_travel_as_of() is None
    
    def test_time_travel_preserves_version_pin(self):
        """Test that time-travel readers preserve version pins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create base snapshot
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu")
            base_manifest = {
                "version": "1.0.0",
                "planes": {"score": {"version": 1}},
            }
            changelog.snapshot_manifest("base_snap", base_manifest)
            
            # Create reader with version pin
            version_pin = {"score": "v1"}
            reader = FeedReader(
                feeds_path=tmpdir,
                verify_schema_on_init=False,
                version_pin=version_pin,
            )
            
            # Time-travel
            time_travel_reader = reader.time_travel(as_of="2026-06-12T12:00:00Z")
            
            # Verify version pin is preserved
            assert time_travel_reader._version_pin == version_pin
    
    def test_time_travel_stores_filter_parameters(self):
        """Test that plane and source filters are stored in time-travel reader."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create base snapshot
            changelog = ManifestChangelog(feeds_root=tmpdir, region="eu")
            base_manifest = {"version": "1.0.0"}
            changelog.snapshot_manifest("base_snap", base_manifest)
            
            reader = FeedReader(
                feeds_path=tmpdir,
                verify_schema_on_init=False,
            )
            
            # Time-travel with specific plane and sources
            time_travel_reader = reader.time_travel(
                as_of="2026-06-12T12:00:00Z",
                plane="score",
                sources=["mackolik", "nesine"],
            )
            
            # Verify stored
            assert time_travel_reader._time_travel_plane == "score"
            assert time_travel_reader._time_travel_sources == ["mackolik", "nesine"]
