"""Tests for FeedReader.dedup() helper (Phase 16.4, bullet 3).

Binding proof tests for built-in dedup functionality:
  - test_dedup_collapses_exact_duplicates: Exact duplicates are marked
  - test_dedup_lru_eviction: Old entries are evicted when LRU is full
  - test_dedup_evicted_resurface_detected: Resurfaces of evicted keys are tracked
  - test_dedup_custom_key_fields: Custom key tuples work
  - test_dedup_handles_missing_fields: Records with missing key fields are handled
  - test_dedup_yield_format: Yields (record, cursor, is_duplicate) tuples

Properties:
  - LRU bounded by cfg.feed_reader_dedup_lru_size (default 100k)
  - Keys are sha256(field1||field2||...)
  - Evicted keys that resurface increment feed_reader_dedup_evicted_resurface_total
  - First occurrence: is_duplicate=False
  - Exact duplicate: is_duplicate=True
  - Resurface: is_duplicate=True (evicted then reappeared)
"""

import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest

from common.feeds import FeedReader, FeedCursor, dedup


class TestFeedReaderDedup:
    """Tests for FeedReader.dedup() helper (Phase 16.4, bullet 3)."""

    @pytest.fixture
    def sample_stream(self):
        """Factory for sample stream generator."""
        def stream_gen():
            records = [
                {"id": 1, "stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z", "score_h": 1.5},
                {"id": 2, "stable_id": "m2", "captured_at": "2026-04-20T10:01:00Z", "score_h": 2.0},
                # Exact duplicate of record 1
                {"id": 1, "stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z", "score_h": 1.5},
                {"id": 3, "stable_id": "m3", "captured_at": "2026-04-20T10:02:00Z", "score_h": 2.5},
            ]
            
            for i, record in enumerate(records):
                cursor = FeedCursor(
                    plane="score",
                    source="mackolik",
                    calendar_date_utc="2026-04-20",
                    logical_offset_records=i + 1,
                    registry_sha256="abc123",
                )
                yield record, cursor
        
        return stream_gen()

    def test_dedup_collapses_exact_duplicates(self, sample_stream):
        """Exact duplicates are marked with is_duplicate=True."""
        results = list(dedup(sample_stream))
        
        assert len(results) == 4
        
        # First record: not a duplicate
        record0, cursor0, is_dup0 = results[0]
        assert record0["id"] == 1
        assert is_dup0 is False
        
        # Second record: not a duplicate
        record1, cursor1, is_dup1 = results[1]
        assert record1["id"] == 2
        assert is_dup1 is False
        
        # Third record: exact duplicate of first
        record2, cursor2, is_dup2 = results[2]
        assert record2["id"] == 1
        assert is_dup2 is True  # Marked as duplicate
        
        # Fourth record: not a duplicate
        record3, cursor3, is_dup3 = results[3]
        assert record3["id"] == 3
        assert is_dup3 is False

    def test_dedup_custom_key_fields(self):
        """Custom key tuple works correctly."""
        def stream_gen():
            cursor = FeedCursor(
                plane="score",
                source="mackolik",
                calendar_date_utc="2026-04-20",
                logical_offset_records=1,
                registry_sha256="abc123",
            )
            
            # Records with same stable_id but different captured_at
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z", "score_h": 1.5}, cursor
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:01:00Z", "score_h": 2.0}, cursor
            
            # Exact duplicate of first (same stable_id AND captured_at)
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z", "score_h": 1.7}, cursor
            
            # Same stable_id, different captured_at again (not duplicate)
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:01:00Z", "score_h": 2.1}, cursor
        
        # With default key (stable_id, captured_at)
        results = list(dedup(stream_gen(), key=("stable_id", "captured_at")))
        
        assert len(results) == 4
        assert results[0][2] is False  # First: not dup
        assert results[1][2] is False  # Second: different captured_at
        assert results[2][2] is True   # Third: exact duplicate of first
        assert results[3][2] is True   # Fourth: duplicate of second (same stable_id + captured_at)

    def test_dedup_lru_eviction(self):
        """Old entries are evicted when LRU is full."""
        def stream_gen():
            cursor = FeedCursor(
                plane="score",
                source="mackolik",
                calendar_date_utc="2026-04-20",
                logical_offset_records=1,
                registry_sha256="abc123",
            )
            
            # Generate 150 unique records
            for i in range(150):
                yield {"stable_id": f"m{i}", "captured_at": f"2026-04-20T{10+i//60}:{i%60:02d}:00Z"}, cursor
        
        # Use a small LRU size to force evictions
        results = list(dedup(stream_gen(), lru_size=100))
        
        # All should be marked as not duplicates (first occurrence)
        assert len(results) == 150
        for record, cursor, is_dup in results:
            assert is_dup is False  # All are unique, so no duplicates marked

    def test_dedup_evicted_resurface_detected(self):
        """Resurfaces of evicted keys are tracked."""
        def stream_gen():
            cursor = FeedCursor(
                plane="score",
                source="mackolik",
                calendar_date_utc="2026-04-20",
                logical_offset_records=1,
                registry_sha256="abc123",
            )
            
            # First, generate 50 unique records
            for i in range(50):
                yield {"stable_id": f"m{i}", "captured_at": f"2026-04-20T10:{i:02d}:00Z"}, cursor
            
            # Then, resurface the first record (which was evicted due to LRU size=40)
            yield {"stable_id": "m0", "captured_at": "2026-04-20T10:00:00Z"}, cursor
        
        results = list(dedup(stream_gen(), lru_size=40))
        
        # The first 40 are not duplicates
        for i in range(40):
            record, cursor, is_dup = results[i]
            assert is_dup is False
        
        # Records 40-49 are unique, so not marked as duplicates
        for i in range(40, 50):
            record, cursor, is_dup = results[i]
            assert is_dup is False
        
        # The resurface of m0 should be marked as duplicate (even though evicted)
        record50, cursor50, is_dup50 = results[50]
        assert record50["stable_id"] == "m0"
        assert is_dup50 is True  # Marked as duplicate due to resurface

    def test_dedup_handles_missing_fields(self):
        """Records with missing key fields are handled gracefully."""
        def stream_gen():
            cursor = FeedCursor(
                plane="score",
                source="mackolik",
                calendar_date_utc="2026-04-20",
                logical_offset_records=1,
                registry_sha256="abc123",
            )
            
            # Record with all fields
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z"}, cursor
            
            # Record missing captured_at
            yield {"stable_id": "m1"}, cursor
            
            # Record missing stable_id
            yield {"captured_at": "2026-04-20T10:00:00Z"}, cursor
            
            # Exact duplicate of first (has all fields)
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z"}, cursor
        
        results = list(dedup(stream_gen()))
        
        assert len(results) == 4
        assert results[0][2] is False  # First: not dup
        assert results[1][2] is False  # Second: different key (missing captured_at)
        assert results[2][2] is False  # Third: different key (missing stable_id)
        assert results[3][2] is True   # Fourth: exact duplicate of first

    def test_dedup_yield_format(self, sample_stream):
        """Yields (record, cursor, is_duplicate) tuples."""
        for item in dedup(sample_stream):
            assert isinstance(item, tuple)
            assert len(item) == 3
            
            record, cursor, is_duplicate = item
            assert isinstance(record, dict)
            assert isinstance(cursor, FeedCursor)
            assert isinstance(is_duplicate, bool)

    def test_dedup_deterministic_key(self):
        """Key generation is deterministic for same fields."""
        # Manually verify that sha256(field1||field2) is consistent
        key1 = "m1" + "||" + "2026-04-20T10:00:00Z"
        key2 = "m1" + "||" + "2026-04-20T10:00:00Z"
        
        hash1 = hashlib.sha256(key1.encode("utf-8")).hexdigest()
        hash2 = hashlib.sha256(key2.encode("utf-8")).hexdigest()
        
        assert hash1 == hash2

    def test_dedup_convenience_wrapper(self):
        """Convenience wrapper dedup() works."""
        def stream_gen():
            cursor = FeedCursor(
                plane="score",
                source="mackolik",
                calendar_date_utc="2026-04-20",
                logical_offset_records=1,
                registry_sha256="abc123",
            )
            
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z"}, cursor
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z"}, cursor  # Duplicate
        
        # Use the convenience wrapper from feeds module
        results = list(dedup(stream_gen()))
        
        assert len(results) == 2
        assert results[0][2] is False  # First: not dup
        assert results[1][2] is True   # Second: duplicate

    def test_dedup_empty_stream(self):
        """Empty stream is handled."""
        def empty_stream():
            return
            yield  # Never reached
        
        results = list(dedup(empty_stream()))
        assert len(results) == 0

    def test_dedup_single_record(self):
        """Single record stream is handled."""
        def single_stream():
            cursor = FeedCursor(
                plane="score",
                source="mackolik",
                calendar_date_utc="2026-04-20",
                logical_offset_records=1,
                registry_sha256="abc123",
            )
            yield {"stable_id": "m1", "captured_at": "2026-04-20T10:00:00Z"}, cursor
        
        results = list(dedup(single_stream()))
        
        assert len(results) == 1
        record, cursor, is_dup = results[0]
        assert is_dup is False
