"""Phase 21.1 §21.1 — Cross-source transfer deduplication.

Collapses duplicate transfers arriving from multiple sources:
  - Dedup key: (player_id, transfer_type, effective_at)
  - Higher confidence wins (official > agreed > rumour)
  - Tie-break: source priority from xops/mock/sources.py (earlier index wins)
  - Window: entire differ cycle (not time-based)

Prevents phantom duplicate features in squad-strength computation when
the same transfer is discovered from both Mackolik feed and club site.

Binding per ROADMAP §21.1 bullet 8 and ENRICHMENT_DATA.md §2.2.
"""

from __future__ import annotations

from typing import Optional
from collections import defaultdict

from ai.common.schemas.records import TransferPayload


# Confidence level ranking (higher = more authoritative)
CONFIDENCE_RANK = {
    "official": 3,
    "agreed": 2,
    "rumour": 1,
}


def get_dedup_key(record: TransferPayload) -> tuple:
    """Extract the deduplication key from a transfer record.
    
    Args:
        record: Transfer payload
        
    Returns:
        Tuple of (player_id, transfer_type, effective_at)
    """
    return (
        record["player_id"],
        record["transfer_type"],
        record["effective_at"],
    )


def should_replace(
    existing_confidence: str,
    existing_source: str,
    new_confidence: str,
    new_source: str,
    source_priority: dict[str, int],
) -> bool:
    """Determine if a new record should replace an existing duplicate.
    
    Args:
        existing_confidence: Confidence of existing record (rumour/agreed/official)
        existing_source: Source of existing record
        new_confidence: Confidence of new record
        new_source: Source of new record
        source_priority: Dict mapping source key to priority index (lower = higher priority)
        
    Returns:
        True if new record should replace existing; False if existing should be kept
    """
    # First criterion: higher confidence wins
    existing_rank = CONFIDENCE_RANK.get(existing_confidence, 0)
    new_rank = CONFIDENCE_RANK.get(new_confidence, 0)
    
    if new_rank > existing_rank:
        # New record has higher confidence
        return True
    elif new_rank < existing_rank:
        # Existing record has higher confidence
        return False
    
    # Tie-break: lower priority index wins (source defined earlier in registry)
    existing_priority = source_priority.get(existing_source, float('inf'))
    new_priority = source_priority.get(new_source, float('inf'))
    
    return new_priority < existing_priority


def deduplicate_transfers(
    records: list[TransferPayload],
    source_priority: Optional[dict[str, int]] = None,
) -> list[TransferPayload]:
    """Deduplicate transfers across sources within a differ cycle.
    
    Collapses duplicate transfers on (player_id, transfer_type, effective_at),
    keeping the highest-confidence version. On tie, uses source priority.
    
    Args:
        records: List of transfer records from all sources
        source_priority: Dict mapping source key to priority (lower = higher priority)
                        If None, all sources treated as equal priority
        
    Returns:
        Deduplicated list of records (one per unique transfer key)
    """
    if source_priority is None:
        source_priority = {}
    
    # Group by dedup key
    dedup_map: dict[tuple, TransferPayload] = {}
    
    for record in records:
        key = get_dedup_key(record)
        
        if key not in dedup_map:
            # First occurrence — add it
            dedup_map[key] = record
        else:
            # Duplicate found — determine which to keep
            existing = dedup_map[key]
            
            existing_confidence = existing.get("confidence", "rumour")
            new_confidence = record.get("confidence", "rumour")
            existing_source = existing.get("source", "unknown")
            new_source = record.get("source", "unknown")
            
            if should_replace(
                existing_confidence,
                existing_source,
                new_confidence,
                new_source,
                source_priority,
            ):
                # Replace with new record
                dedup_map[key] = record
    
    # Return deduplicated records in original order
    return list(dedup_map.values())


__all__ = [
    "get_dedup_key",
    "should_replace",
    "deduplicate_transfers",
    "CONFIDENCE_RANK",
]
