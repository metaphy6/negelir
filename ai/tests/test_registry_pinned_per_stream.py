"""Test that registry is frozen at stream-open time (Phase 16.1, ledger #3).

Core requirement: Every FeedReader.stream() and snapshot() call should snap
the registry SHA256 at open time and pin it through the iterator's lifetime.
Mid-stream registry edits must not affect an open reader.
"""

import hashlib
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open

from ai.common.feeds import FeedReader, FeedCursor


def test_registry_pinned_per_stream_captures_sha():
    """Verify that stream() captures registry SHA at open time."""
    reader = FeedReader()
    
    # Create a stream and get the first record + cursor
    cursor: FeedCursor | None = None
    for record, cursor in reader.stream("score", sources=["all"]):
        break  # Just get the first result
    
    # Cursor should have the registry SHA captured
    assert cursor is not None
    assert cursor.registry_sha256, "Cursor should include registry_sha256"
    assert len(cursor.registry_sha256) == 64, "SHA256 should be 64 hex chars"
    assert cursor.plane == "score"


def test_registry_pinned_per_stream_detects_drift():
    """Verify that resuming with mismatched registry SHA raises error."""
    reader = FeedReader()
    
    # Create a cursor with a different (fake) registry SHA
    fake_cursor = FeedCursor(
        plane="score",
        source="all",
        calendar_date_utc="2026-04-20",
        registry_sha256="0" * 64,  # Deliberately wrong SHA
    )
    
    # Attempting to resume should raise ValueError due to registry drift
    with pytest.raises(ValueError, match="Registry SHA mismatch"):
        for record, cursor in reader.stream("score", cursor=fake_cursor):
            break


def test_registry_pinned_per_snapshot():
    """Verify that snapshot() also captures registry SHA at open time."""
    reader = FeedReader()
    
    # Create a snapshot and inspect the records
    registry_sha_in_record = None
    for record in reader.snapshot("score"):
        # snapshot() yields records with the registry_sha embedded
        registry_sha_in_record = record.get("registry_sha")
        break
    
    assert registry_sha_in_record, "Snapshot record should include registry_sha"
    assert len(registry_sha_in_record) == 64, "SHA256 should be 64 hex chars"


def test_registry_sha_is_stable():
    """Verify that multiple calls to stream() produce the same registry SHA."""
    reader = FeedReader()
    
    # Collect registry SHA from two separate stream() calls
    sha_list = []
    for i in range(2):
        for record, cursor in reader.stream("schedule", sources=["all"]):
            sha_list.append(cursor.registry_sha256)
            break
    
    assert len(sha_list) == 2
    assert sha_list[0] == sha_list[1], "Registry SHA should be stable across calls"


def test_feed_cursor_has_registry_sha_field():
    """Verify FeedCursor dataclass includes registry_sha256 field."""
    cursor = FeedCursor(
        plane="score",
        source="mackolik",
        calendar_date_utc="2026-04-20",
        registry_sha256="abc123" * 10 + "ab",  # 64 chars
    )
    
    assert hasattr(cursor, "registry_sha256")
    assert cursor.registry_sha256 == "abc123" * 10 + "ab"
    assert cursor.plane == "score"
    assert cursor.source == "mackolik"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
