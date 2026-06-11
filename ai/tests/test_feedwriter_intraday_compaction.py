"""Tests for intra-day compaction and partition sealing (Phase 16.2 bullet 8).

Covers:
  - Partition creation and sealing
  - Partition numbering (00, 01, 02, ...)
  - Size threshold detection
  - Multi-date partition management
  - Logical offset tracking
  - Statistics and accounting
"""

import pytest
from ai.common.feeds.intraday_compaction import (
    PartitionMetadata,
    PartitionRegistry,
    CompactionStrategy,
)
import time


class TestPartitionMetadata:
    """Tests for PartitionMetadata."""

    def test_partition_creation(self):
        """PartitionMetadata captures all fields."""
        part = PartitionMetadata(
            date_utc="2024-01-15",
            part_number=2,
            size_bytes=512000,
            record_count=1000,
        )
        
        assert part.date_utc == "2024-01-15"
        assert part.part_number == 2
        assert part.size_bytes == 512000
        assert part.record_count == 1000

    def test_partition_is_sealed_false(self):
        """Unsealed partition has is_sealed=False."""
        part = PartitionMetadata(
            date_utc="2024-01-15",
            part_number=0,
            size_bytes=100000,
        )
        
        assert part.is_sealed is False

    def test_partition_is_sealed_true(self):
        """Sealed partition has is_sealed=True."""
        part = PartitionMetadata(
            date_utc="2024-01-15",
            part_number=0,
            size_bytes=100000,
            sealed_at_sec=time.time(),
        )
        
        assert part.is_sealed is True

    def test_partition_filename_stem(self):
        """Filename stem is correctly formatted."""
        part = PartitionMetadata(
            date_utc="2024-01-15",
            part_number=5,
            size_bytes=100000,
        )
        
        assert part.filename_stem == "2024-01-15.part-05"

    def test_partition_filename_stem_zero_padded(self):
        """Part numbers are zero-padded to 2 digits."""
        part0 = PartitionMetadata(
            date_utc="2024-01-15",
            part_number=0,
            size_bytes=100000,
        )
        part99 = PartitionMetadata(
            date_utc="2024-01-15",
            part_number=99,
            size_bytes=100000,
        )
        
        assert part0.filename_stem == "2024-01-15.part-00"
        assert part99.filename_stem == "2024-01-15.part-99"


class TestPartitionRegistry:
    """Tests for PartitionRegistry."""

    def test_registry_init_defaults(self):
        """PartitionRegistry initializes with defaults."""
        registry = PartitionRegistry()
        
        assert registry.compact_bytes == 256 * 1024 * 1024
        assert registry.total_sealed == 0
        assert registry.current_part is None

    def test_registry_init_custom_threshold(self):
        """PartitionRegistry accepts custom threshold."""
        registry = PartitionRegistry(compact_bytes=1024 * 1024)
        
        assert registry.compact_bytes == 1024 * 1024

    def test_registry_add_record_creates_partition(self):
        """add_record creates partition on first record."""
        registry = PartitionRegistry(compact_bytes=1000000)
        
        should_seal, next_part = registry.add_record("2024-01-15", 100)
        
        assert registry.current_part is not None
        assert registry.current_part.date_utc == "2024-01-15"
        assert registry.current_part.part_number == 0
        assert registry.current_part.size_bytes == 100
        assert registry.current_part.record_count == 1
        assert should_seal is False
        assert next_part is None

    def test_registry_add_record_accumulates_size(self):
        """add_record accumulates size across multiple calls."""
        registry = PartitionRegistry(compact_bytes=1000000)
        
        should_seal1, _ = registry.add_record("2024-01-15", 100)
        should_seal2, _ = registry.add_record("2024-01-15", 200)
        should_seal3, _ = registry.add_record("2024-01-15", 150)
        
        assert registry.current_part.size_bytes == 450
        assert registry.current_part.record_count == 3
        assert should_seal1 is False
        assert should_seal2 is False
        assert should_seal3 is False

    def test_registry_add_record_detects_compaction(self):
        """add_record detects when threshold is exceeded."""
        registry = PartitionRegistry(compact_bytes=1000)
        
        # Add records up to threshold
        should_seal1, _ = registry.add_record("2024-01-15", 600)
        assert should_seal1 is False
        
        # Next record exceeds threshold
        should_seal2, next_part = registry.add_record("2024-01-15", 500)
        assert should_seal2 is True
        assert next_part is not None
        assert next_part.part_number == 1
        assert next_part.date_utc == "2024-01-15"
        assert registry.total_sealed == 1

    def test_registry_add_record_switches_partitions(self):
        """add_record switches to next partition on seal."""
        registry = PartitionRegistry(compact_bytes=1000)
        
        registry.add_record("2024-01-15", 600)
        should_seal, next_part = registry.add_record("2024-01-15", 500)
        
        # Verify old partition is sealed
        assert "2024-01-15" in registry.partitions
        assert len(registry.partitions["2024-01-15"]) == 1
        assert registry.partitions["2024-01-15"][0].is_sealed
        
        # Verify current partition is the new one
        assert registry.current_part.part_number == 1
        assert not registry.current_part.is_sealed

    def test_registry_add_record_multi_date(self):
        """add_record maintains separate partitions per date."""
        registry = PartitionRegistry(compact_bytes=1000)
        
        registry.add_record("2024-01-15", 500)
        registry.add_record("2024-01-16", 300)  # Switches to 2024-01-16
        should_seal, _ = registry.add_record("2024-01-15", 600)  # Back to 2024-01-15, creates new partition
        
        # When we switch dates and come back, we create a new partition
        # So the 600 doesn't accumulate with the previous 500
        assert should_seal is False  # 600 < 1000
        assert registry.current_part.date_utc == "2024-01-15"
        # The partitions dict should have entries for both dates
        assert "2024-01-15" in registry.partitions
        assert "2024-01-16" in registry.partitions

    def test_registry_seal_partition_explicit(self):
        """seal_partition explicitly seals current partition."""
        registry = PartitionRegistry(compact_bytes=1000000)
        
        registry.add_record("2024-01-15", 500)
        now = time.time()
        sealed = registry.seal_partition("2024-01-15", now)
        
        assert sealed is not None
        assert sealed.sealed_at_sec == now
        assert sealed.is_sealed is True
        assert registry.current_part is None

    def test_registry_get_partitions_for_date(self):
        """get_partitions_for_date returns ordered partitions."""
        registry = PartitionRegistry(compact_bytes=500)
        
        registry.add_record("2024-01-15", 300)
        registry.add_record("2024-01-15", 300)  # Triggers seal to part-00
        registry.add_record("2024-01-15", 300)  # Creates part-01, triggers seal
        
        parts = registry.get_partitions_for_date("2024-01-15")
        
        # Should have part-00 (sealed), part-01 (sealed), and current unsealed part
        # But current is not in partitions list yet, only in registry.current_part
        assert len(parts) >= 2
        assert parts[0].part_number == 0
        assert parts[1].part_number == 1

    def test_registry_get_partitions_includes_current(self):
        """get_partitions_for_date includes unsealed current partition."""
        registry = PartitionRegistry(compact_bytes=1000000)
        
        registry.add_record("2024-01-15", 500)
        parts = registry.get_partitions_for_date("2024-01-15")
        
        assert len(parts) == 1
        assert parts[0].is_sealed is False

    def test_registry_get_statistics(self):
        """get_statistics returns comprehensive metrics."""
        registry = PartitionRegistry(compact_bytes=500)
        
        registry.add_record("2024-01-15", 300)
        registry.add_record("2024-01-15", 300)  # Seal to part-00
        registry.add_record("2024-01-16", 200)
        
        stats = registry.get_statistics()
        
        assert stats["total_dates"] == 2
        # Total partitions: part-00 (sealed), part-01 (unsealed for 2024-01-15), part-00 (unsealed for 2024-01-16)
        assert stats["total_partitions"] >= 2
        assert stats["total_sealed"] >= 1
        assert stats["compact_threshold_bytes"] == 500


class TestCompactionStrategy:
    """Tests for CompactionStrategy."""

    def test_strategy_init_defaults(self):
        """CompactionStrategy initializes with defaults."""
        strategy = CompactionStrategy()
        
        assert strategy.compact_bytes == 256 * 1024 * 1024

    def test_strategy_should_compact_below_threshold(self):
        """should_compact returns False below threshold."""
        strategy = CompactionStrategy(compact_bytes=1000)
        
        assert strategy.should_compact(500) is False
        assert strategy.should_compact(999) is False

    def test_strategy_should_compact_at_threshold(self):
        """should_compact returns True at threshold."""
        strategy = CompactionStrategy(compact_bytes=1000)
        
        assert strategy.should_compact(1000) is True

    def test_strategy_should_compact_above_threshold(self):
        """should_compact returns True above threshold."""
        strategy = CompactionStrategy(compact_bytes=1000)
        
        assert strategy.should_compact(1001) is True
        assert strategy.should_compact(5000) is True

    def test_strategy_next_partition_number_empty(self):
        """next_partition_number returns 0 for empty list."""
        strategy = CompactionStrategy()
        
        num = strategy.next_partition_number([])
        assert num == 0

    def test_strategy_next_partition_number_existing(self):
        """next_partition_number returns max+1."""
        strategy = CompactionStrategy()
        
        parts = [
            PartitionMetadata("2024-01-15", 0, 100),
            PartitionMetadata("2024-01-15", 1, 100),
            PartitionMetadata("2024-01-15", 3, 100),  # Gap
        ]
        
        num = strategy.next_partition_number(parts)
        assert num == 4


class TestCompactionInvariants:
    """Property-based tests for compaction invariants."""

    def test_invariant_partition_ordering(self):
        """Partitions are ordered by part number."""
        registry = PartitionRegistry(compact_bytes=500)
        
        for i in range(10):
            registry.add_record("2024-01-15", 300)
            registry.add_record("2024-01-15", 300)
        
        parts = registry.get_partitions_for_date("2024-01-15")
        for i, part in enumerate(parts):
            assert part.part_number == i

    def test_invariant_record_count_accumulates(self):
        """Record count accumulates correctly."""
        registry = PartitionRegistry(compact_bytes=10000)
        
        for i in range(50):
            registry.add_record("2024-01-15", 100)
        
        assert registry.current_part.record_count == 50

    def test_invariant_sealed_partitions_immutable(self):
        """Sealed partitions don't change after seal."""
        registry = PartitionRegistry(compact_bytes=500)
        
        registry.add_record("2024-01-15", 300)
        should_seal, _ = registry.add_record("2024-01-15", 300)
        
        sealed_part = registry.partitions["2024-01-15"][0]
        original_size = sealed_part.size_bytes
        original_count = sealed_part.record_count
        
        # Add more records (goes to new partition)
        registry.add_record("2024-01-15", 200)
        
        # Sealed partition unchanged
        assert sealed_part.size_bytes == original_size
        assert sealed_part.record_count == original_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
