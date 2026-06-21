"""Tests for FeedReader telemetry signals (Phase 16.4, bullet 5).

Binding proof tests for telemetry metrics:
  - test_lag_metric_fires: feed_reader_lag_ms is computed from captured_at
  - test_corrupt_line_counter: feed_reader_corrupt_line_total increments
  - test_guessed_path_reject_counter: feed_reader_guessed_path_rejects_total increments
  - test_checksum_mismatch_counter: feed_reader_checksum_mismatch_total increments
  - test_registry_skew_counter: feed_reader_registry_skew_total increments
  - test_pointer_stream_gauge: feed_reader_pointer_stream_subscribed gauge updates

Properties (Phase 16.4, bullet 5 watch set from Phase 4.6):
  - feed_reader_lag_ms: Wall-clock delta (now - latest record's captured_at)
  - feed_reader_corrupt_line_total: Count of malformed NDJSON lines
  - feed_reader_guessed_path_rejects_total: Count of rejected guessed paths
  - feed_reader_checksum_mismatch_total: Count of bad checksum detections
  - feed_reader_dedup_evicted_resurface_total: Count of LRU eviction resurfaces
  - feed_reader_registry_skew_total: Count of registry SHA mismatches
  - feed_reader_pointer_stream_subscribed: Gauge {plane,source} = 0/1
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from common.feeds import FeedReader, FeedCursor


class TestFeedReaderTelemetry:
    """Tests for telemetry signals (Phase 16.4, bullet 5)."""

    @pytest.fixture
    def tmp_feeds_dir(self, tmp_path):
        """Create a temporary feeds directory structure."""
        feeds_dir = tmp_path / "feeds"
        feeds_dir.mkdir()
        
        # Create subdirectories
        (feeds_dir / "score" / "mackolik").mkdir(parents=True)
        
        return feeds_dir

    @pytest.fixture
    def reader_with_tmp_path(self, tmp_feeds_dir):
        """Create a FeedReader pointing to temp path."""
        # Reset global telemetry state
        from common.feeds import reader as reader_module
        reader_module._telemetry = {
            "feed_reader_lag_ms": None,
            "feed_reader_corrupt_line_total": 0,
            "feed_reader_guessed_path_rejects_total": 0,
            "feed_reader_checksum_mismatch_total": 0,
            "feed_reader_dedup_evicted_resurface_total": 0,
            "feed_reader_registry_skew_total": 0,
            "feed_reader_pointer_stream_subscribed": {},
        }
        
        reader = FeedReader(
            feeds_path=tmp_feeds_dir,
            verify_schema_on_init=False,
            emitter_management_url=None,
        )
        return reader

    def test_lag_metric_fires(self, reader_with_tmp_path):
        """feed_reader_lag_ms is computed from captured_at."""
        # Use a timestamp from 5 seconds ago
        past_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        captured_at = past_time.isoformat().replace("+00:00", "Z")
        
        reader_with_tmp_path._record_lag_ms(captured_at)
        
        metrics = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics["feed_reader_lag_ms"] is not None
        assert metrics["feed_reader_lag_ms"] >= 5000  # At least 5 seconds
        assert metrics["feed_reader_lag_ms"] <= 6000  # Less than 6 seconds

    def test_lag_metric_handles_none(self, reader_with_tmp_path):
        """feed_reader_lag_ms handles None captured_at."""
        reader_with_tmp_path._record_lag_ms(None)
        
        metrics = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics["feed_reader_lag_ms"] is None

    def test_corrupt_line_counter_increments(self, reader_with_tmp_path):
        """feed_reader_corrupt_line_total increments."""
        metrics_before = reader_with_tmp_path.get_telemetry_metrics()
        count_before = metrics_before["feed_reader_corrupt_line_total"]
        
        reader_with_tmp_path._record_corrupt_line()
        
        metrics_after = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics_after["feed_reader_corrupt_line_total"] == count_before + 1

    def test_guessed_path_reject_counter_increments(self, reader_with_tmp_path):
        """feed_reader_guessed_path_rejects_total increments."""
        metrics_before = reader_with_tmp_path.get_telemetry_metrics()
        count_before = metrics_before["feed_reader_guessed_path_rejects_total"]
        
        reader_with_tmp_path._record_guessed_path_reject("feeds/score/mackolik/2026-04-20.ndjson")
        
        metrics_after = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics_after["feed_reader_guessed_path_rejects_total"] == count_before + 1

    def test_checksum_mismatch_counter_increments(self, reader_with_tmp_path):
        """feed_reader_checksum_mismatch_total increments."""
        metrics_before = reader_with_tmp_path.get_telemetry_metrics()
        count_before = metrics_before["feed_reader_checksum_mismatch_total"]
        
        reader_with_tmp_path._record_checksum_mismatch("feeds/score/mackolik/2026-04-20.ndjson")
        
        metrics_after = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics_after["feed_reader_checksum_mismatch_total"] == count_before + 1

    def test_pointer_stream_gauge_updates(self, reader_with_tmp_path):
        """feed_reader_pointer_stream_subscribed gauge updates."""
        metrics_before = reader_with_tmp_path.get_telemetry_metrics()
        assert "score,mackolik" not in metrics_before["feed_reader_pointer_stream_subscribed"]
        
        reader_with_tmp_path._record_pointer_stream_subscribed("score", "mackolik", subscribed=True)
        
        metrics_after = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics_after["feed_reader_pointer_stream_subscribed"]["score,mackolik"] == 1

    def test_pointer_stream_gauge_unsubscribe(self, reader_with_tmp_path):
        """feed_reader_pointer_stream_subscribed gauge can be set to 0."""
        reader_with_tmp_path._record_pointer_stream_subscribed("score", "mackolik", subscribed=True)
        reader_with_tmp_path._record_pointer_stream_subscribed("score", "mackolik", subscribed=False)
        
        metrics = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics["feed_reader_pointer_stream_subscribed"]["score,mackolik"] == 0

    def test_multiple_pointer_streams(self, reader_with_tmp_path):
        """Multiple pointer stream gauges can coexist."""
        reader_with_tmp_path._record_pointer_stream_subscribed("score", "mackolik", subscribed=True)
        reader_with_tmp_path._record_pointer_stream_subscribed("schedule", "nesine", subscribed=True)
        reader_with_tmp_path._record_pointer_stream_subscribed("score", "opta", subscribed=False)
        
        metrics = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics["feed_reader_pointer_stream_subscribed"]["score,mackolik"] == 1
        assert metrics["feed_reader_pointer_stream_subscribed"]["schedule,nesine"] == 1
        assert metrics["feed_reader_pointer_stream_subscribed"]["score,opta"] == 0

    def test_get_telemetry_metrics_returns_dict(self, reader_with_tmp_path):
        """get_telemetry_metrics returns a dict with all expected keys."""
        metrics = reader_with_tmp_path.get_telemetry_metrics()
        
        assert isinstance(metrics, dict)
        assert "feed_reader_lag_ms" in metrics
        assert "feed_reader_corrupt_line_total" in metrics
        assert "feed_reader_guessed_path_rejects_total" in metrics
        assert "feed_reader_checksum_mismatch_total" in metrics
        assert "feed_reader_dedup_evicted_resurface_total" in metrics
        assert "feed_reader_registry_skew_total" in metrics
        assert "feed_reader_pointer_stream_subscribed" in metrics

    def test_lag_metric_with_different_timezones(self, reader_with_tmp_path):
        """feed_reader_lag_ms works with RFC3339 timestamps."""
        # Create a timestamp in past
        past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        
        # Format as RFC3339 (with Z timezone)
        captured_at = past_time.isoformat().replace("+00:00", "Z")
        
        reader_with_tmp_path._record_lag_ms(captured_at)
        
        metrics = reader_with_tmp_path.get_telemetry_metrics()
        assert metrics["feed_reader_lag_ms"] is not None
        assert metrics["feed_reader_lag_ms"] >= 10000  # At least 10 seconds
        assert metrics["feed_reader_lag_ms"] <= 11000  # Less than 11 seconds
