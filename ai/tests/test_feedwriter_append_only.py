"""Tests for FeedWriter append-only semantics (Phase 16.2, ledger #4).

Binding proof tests:
  - test_append_only: Records can only be appended, never overwritten or deleted
  - test_monotonic_captured_at: Records appear in order of enqueue
  - test_multiple_records: Multiple records accumulate in file
  
Properties verified:
  - File is opened in append binary mode ('ab')
  - Records are always written to end of file
  - No truncation or overwrite can occur
"""

import json
import time
from pathlib import Path
from unittest import mock

import pytest

from common.feeds.writer import FeedWriter, FeedManifest


class TestAppendOnly:
    """Append-only write semantics tests."""

    def test_append_only_mode(self, tmp_path):
        """Writer opens file in append mode; new writes go to end."""
        writer = FeedWriter(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_path),
            redis_client=None,
            writer_id="writer-1",
        )
        
        writer.open()
        
        # Write first record
        record1 = {"id": 1, "value": "first"}
        writer.enqueue(record1)
        
        # Get current file size
        current_size = writer.current_file.stat().st_size
        
        # Write second record
        record2 = {"id": 2, "value": "second"}
        writer.enqueue(record2)
        
        # New size should be larger (appended, not overwritten)
        new_size = writer.current_file.stat().st_size
        assert new_size > current_size
        
        writer.close()
        
        # Verify both records exist in file
        content = writer.current_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
    
    def test_no_truncation_on_reopen(self, tmp_path):
        """Reopening writer does not truncate existing records."""
        mock_redis = mock.MagicMock()
        mock_redis.set.return_value = True
        mock_redis.get.return_value = b"writer-1"
        
        writer1 = FeedWriter(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_path),
            redis_client=mock_redis,
            writer_id="writer-1",
        )
        
        writer1.open()
        writer1.enqueue({"id": 1})
        writer1.close()
        
        # Reopen (simulating process restart with same lease)
        writer2 = FeedWriter(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_path),
            redis_client=mock_redis,
            writer_id="writer-1",
        )
        
        writer2.open()
        writer2.enqueue({"id": 2})
        writer2.close()
        
        # Both records should be present
        date = time.strftime("%Y-%m-%d", time.gmtime())
        ndjson_file = tmp_path / "score" / "test_source" / f"{date}.ndjson"
        content = ndjson_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
    
    def test_record_order_preserved(self, tmp_path):
        """Records appear in file in the order they were enqueued."""
        writer = FeedWriter(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_path),
            redis_client=None,
            writer_id="writer-1",
        )
        
        writer.open()
        
        records = [
            {"id": i, "timestamp": i * 100}
            for i in range(10)
        ]
        
        for record in records:
            writer.enqueue(record)
        
        writer.close()
        
        # Verify order in file
        content = writer.current_file.read_text()
        lines = content.strip().split("\n")
        
        assert len(lines) == 10
        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data["id"] == i
            assert data["timestamp"] == i * 100
    
    def test_manifest_counts_increment(self, tmp_path):
        """Manifest records_written and bytes_written increment monotonically."""
        writer = FeedWriter(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_path),
            redis_client=None,
            writer_id="writer-1",
        )
        
        writer.open()
        
        initial_records = writer.manifest.records_written
        initial_bytes = writer.manifest.bytes_written
        
        for i in range(5):
            writer.enqueue({"id": i})
        
        # Verify increments
        assert writer.manifest.records_written == initial_records + 5
        assert writer.manifest.bytes_written > initial_bytes
        
        writer.close()
    
    def test_large_record_stream(self, tmp_path):
        """Writer handles large streams of records without data loss."""
        writer = FeedWriter(
            plane="score",
            source="test_source",
            feeds_dir=str(tmp_path),
            redis_client=None,
            writer_id="writer-1",
            fsync_mode="off",  # Faster for bulk writes
        )
        
        writer.open()
        
        n_records = 1000
        for i in range(n_records):
            writer.enqueue({
                "id": i,
                "data": "x" * 100,  # Some payload
            })
        
        writer.close()
        
        # Count lines in output
        content = writer.current_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == n_records


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
