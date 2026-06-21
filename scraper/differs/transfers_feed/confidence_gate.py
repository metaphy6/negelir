"""Phase 21.1 §21.1 — Confidence gate for roster-state storage.

Enforces confidence-based rules for transfer record persistence:
  - `rumour` → editorial-plane sentiment only; no roster-state write
  - `agreed` → provisional roster-state write; flag `provisional=true`
  - `official` → final roster-state write; clears `provisional` on any
                 earlier `agreed` row for the same player

The confidence gate is the first filter applied to any transfer record
before it reaches the storage layer. Storage writers call `should_write()`
and `get_write_mode()` to determine which rows to persist and with what flags.

Binding per ROADMAP §21.1 bullet 4 and ENRICHMENT_DATA.md §2.4 freshness rules.
"""

from __future__ import annotations

from typing import Literal, TypedDict, Optional
from datetime import datetime

from common.schemas.records import TransferPayload


class RosterStateWriteInstruction(TypedDict):
    """Instruction for how to write a roster-state record to storage."""
    
    should_write: bool
    """True if record should be written to roster-state; False for rumour."""
    
    provisional: bool
    """True if this is an 'agreed' record that is not yet official."""
    
    clear_provisional_for_player: Optional[str]
    """If set to a player_id, clear the `provisional` flag on that player's
    earlier 'agreed' records (used when an 'official' record arrives)."""
    
    confidence_level: Literal["rumour", "agreed", "official"]
    """The confidence level of this record (for logging/audit)."""


def should_write(record: TransferPayload) -> bool:
    """Determine if a record should be written to roster-state storage.
    
    Args:
        record: Transfer record with confidence level
        
    Returns:
        True if should write to roster-state (confidence in ["agreed", "official"])
        False if should skip roster-state (confidence="rumour")
    """
    return record["confidence"] in ("agreed", "official")


def get_write_mode(record: TransferPayload) -> RosterStateWriteInstruction:
    """Get the write instruction for a transfer record.
    
    Determines whether to write to roster-state, whether to mark as provisional,
    and whether to clear provisional flags on earlier records.
    
    Args:
        record: Transfer record with confidence level
        
    Returns:
        RosterStateWriteInstruction specifying write mode and flags
    """
    confidence = record["confidence"]
    
    if confidence == "rumour":
        # Rumours do not reach roster-state
        return {
            "should_write": False,
            "provisional": False,
            "clear_provisional_for_player": None,
            "confidence_level": "rumour",
        }
    
    elif confidence == "agreed":
        # Agreed transfers reach roster-state but marked as provisional
        return {
            "should_write": True,
            "provisional": True,
            "clear_provisional_for_player": None,
            "confidence_level": "agreed",
        }
    
    elif confidence == "official":
        # Official transfers are final; clear provisional on earlier agreed records
        # for the same player
        return {
            "should_write": True,
            "provisional": False,
            "clear_provisional_for_player": record["player_id"],
            "confidence_level": "official",
        }
    
    else:
        # Defensive: unknown confidence level treated as rumour (no write)
        raise ValueError(f"Unknown confidence level: {confidence}")


def apply_gate(record: TransferPayload) -> RosterStateWriteInstruction:
    """Apply the confidence gate to a transfer record.
    
    This is the main entry point for the storage writer.
    
    Args:
        record: Transfer record with confidence level
        
    Returns:
        RosterStateWriteInstruction with all flags and write mode
        
    Raises:
        ValueError: If confidence level is invalid
    """
    if "confidence" not in record:
        raise ValueError("Transfer record missing required 'confidence' field")
    
    return get_write_mode(record)


__all__ = [
    "RosterStateWriteInstruction",
    "should_write",
    "get_write_mode",
    "apply_gate",
]
