"""Intra-day compaction: partition sealing when size threshold exceeded (Phase 16.2 bullet 8).

When a hot `.ndjson` file exceeds cfg.emitter_intraday_compact_bytes (default 256 MiB):
  1. Rotate to <date>.part-NN.ndjson (sealed, compressed, sidecar)
  2. Continue into <date>.part-NN+1.ndjson (new hot file)
  
Reader treats parts as logical concatenation in order. Cursor's logical_offset_records
spans all parts of the same date.

Properties (binding per Phase 16.2):
  - Partition numbering: NN starts at 00, increments on each seal
  - Each part: compressed + SHA256 sidecar + atomic rename
  - Manifest records all parts for a date
  - Atomic transition: old part unsealed → sealed, new part created in same tick
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import re


@dataclass
class PartitionMetadata:
    """Metadata for one partition."""
    date_utc: str  # YYYY-MM-DD
    part_number: int  # 0, 1, 2, ...
    size_bytes: int
    record_count: int = 0
    sealed_at_sec: Optional[float] = None  # None if hot (unsealed)
    
    @property
    def is_sealed(self) -> bool:
        """Check if partition is sealed."""
        return self.sealed_at_sec is not None
    
    @property
    def filename_stem(self) -> str:
        """Generate filename stem (without extension)."""
        return f"{self.date_utc}.part-{self.part_number:02d}"


class PartitionRegistry:
    """Registry and management of partitions for a (plane, source)."""
    
    def __init__(self, compact_bytes: int = 256 * 1024 * 1024):
        """Initialize partition registry.
        
        Args:
            compact_bytes: Size threshold for sealing a partition (default 256 MiB)
        """
        self.compact_bytes = compact_bytes
        self.partitions: dict[str, list[PartitionMetadata]] = {}  # date -> [PartitionMetadata, ...]
        self.current_part: Optional[PartitionMetadata] = None
        self.total_sealed = 0
    
    def add_record(self, date_utc: str, record_size: int) -> Tuple[bool, Optional[PartitionMetadata]]:
        """Add a record and check if compaction is needed.
        
        Args:
            date_utc: Record's date (YYYY-MM-DD)
            record_size: Size of the record in bytes
            
        Returns:
            Tuple of (should_seal_current, next_partition)
            - should_seal_current: True if current partition exceeds threshold
            - next_partition: The new partition to write to (or None if no seal needed)
        """
        # Initialize partition for this date if needed
        if date_utc not in self.partitions:
            self.partitions[date_utc] = []
        
        # Create current partition if needed
        if self.current_part is None or self.current_part.date_utc != date_utc:
            # Get next part number for this date
            part_num = len(self.partitions[date_utc])
            self.current_part = PartitionMetadata(
                date_utc=date_utc,
                part_number=part_num,
                size_bytes=0,
            )
        
        # Add record to current partition
        self.current_part.size_bytes += record_size
        self.current_part.record_count += 1
        
        # Check if we need to seal
        should_seal = self.current_part.size_bytes >= self.compact_bytes
        
        if should_seal:
            # Seal current partition
            self.current_part.sealed_at_sec = 0  # Placeholder; caller fills in real timestamp
            self.partitions[date_utc].append(self.current_part)
            self.total_sealed += 1
            
            # Create next partition
            next_part = PartitionMetadata(
                date_utc=date_utc,
                part_number=len(self.partitions[date_utc]),
                size_bytes=0,
            )
            self.current_part = next_part
            
            return True, next_part
        
        return False, None
    
    def seal_partition(self, date_utc: str, sealed_at_sec: float) -> Optional[PartitionMetadata]:
        """Explicitly seal the current partition (e.g., at day boundary).
        
        Args:
            date_utc: Date to seal partitions for
            sealed_at_sec: Timestamp of seal
            
        Returns:
            The sealed partition, or None if no current partition
        """
        if self.current_part is None or self.current_part.date_utc != date_utc:
            return None
        
        self.current_part.sealed_at_sec = sealed_at_sec
        self.partitions[date_utc].append(self.current_part)
        self.total_sealed += 1
        
        self.current_part = None
        return self.partitions[date_utc][-1]
    
    def get_partitions_for_date(self, date_utc: str) -> list[PartitionMetadata]:
        """Get all partitions (sealed + current) for a date.
        
        Args:
            date_utc: Date to query
            
        Returns:
            List of PartitionMetadata, ordered by part number
        """
        parts = self.partitions.get(date_utc, [])
        
        # Include current partition if it matches the date
        if self.current_part and self.current_part.date_utc == date_utc:
            parts = parts + [self.current_part]
        
        return sorted(parts, key=lambda p: p.part_number)
    
    def get_statistics(self) -> dict:
        """Get partition registry statistics."""
        total_parts = sum(len(parts) for parts in self.partitions.values())
        if self.current_part:
            total_parts += 1
        
        return {
            "total_dates": len(self.partitions),
            "total_partitions": total_parts,
            "total_sealed": self.total_sealed,
            "current_part_size_bytes": self.current_part.size_bytes if self.current_part else 0,
            "compact_threshold_bytes": self.compact_bytes,
        }


class CompactionStrategy:
    """Strategy for when/how to trigger intra-day compaction."""
    
    def __init__(self, compact_bytes: int = 256 * 1024 * 1024):
        """Initialize compaction strategy.
        
        Args:
            compact_bytes: Size threshold
        """
        self.compact_bytes = compact_bytes
    
    def should_compact(self, current_size: int) -> bool:
        """Determine if a partition should be sealed.
        
        Args:
            current_size: Current size of the partition in bytes
            
        Returns:
            True if size >= threshold
        """
        return current_size >= self.compact_bytes
    
    def next_partition_number(self, existing_parts: list[PartitionMetadata]) -> int:
        """Calculate next partition number.
        
        Args:
            existing_parts: List of existing parts for a date
            
        Returns:
            Next partition number
        """
        if not existing_parts:
            return 0
        
        max_num = max(p.part_number for p in existing_parts)
        return max_num + 1
