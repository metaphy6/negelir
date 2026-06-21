"""Phase 21.1 §21.1 — Suspension record lifecycle management.

Manages the lifecycle of suspension records (competition-scoped):
  - Track matches_remaining (decremented by post-match reactor)
  - Determine expiration: both expires_after_match_id resolved AND matches_remaining = 0
  - Query active suspensions (non-expired) for a player

Suspension records are immutable once created; lifecycle state is external
(in storage layer or bus topic). This module computes expiration logic only.

Binding per ROADMAP §21.1 bullet 7 and ENRICHMENT_DATA.md §2.1.
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone


class SuspensionState:
    """Computed state of a suspension record."""
    
    is_active: bool
    """True if suspension still applies; False if expired."""
    
    matches_remaining: int
    """Current remaining match count."""
    
    expires_after_match_id: Optional[str]
    """Match ID after which this suspension expires (or None if indefinite)."""
    
    reason: str
    """Reason for suspension (e.g., 'accumulated_yellows', 'red')."""


def should_expire(
    matches_remaining: int,
    expires_after_match_id: Optional[str],
    resolved_match_id: Optional[str] = None,
) -> bool:
    """Determine if a suspension should expire.
    
    A suspension expires when BOTH:
      1. matches_remaining reaches 0
      2. expires_after_match_id has been resolved (match played)
    
    Args:
        matches_remaining: Current remaining match count
        expires_after_match_id: Match ID after which suspension expires (or None)
        resolved_match_id: The ID of the most recently completed match (or None if unknown)
        
    Returns:
        True if suspension should expire; False if still active
    """
    # If matches_remaining > 0, still active
    if matches_remaining > 0:
        return False
    
    # matches_remaining == 0; now check if the trigger match has resolved
    if expires_after_match_id is None:
        # No specific match trigger — expire when matches_remaining = 0
        return True
    
    if resolved_match_id is None:
        # We don't know if the trigger match has resolved — keep active (conservative)
        return False
    
    # Check if the trigger match has been resolved
    # resolved_match_id is the most recent match; if it matches or is after expires_after_match_id
    return resolved_match_id >= expires_after_match_id


def decrement_matches_remaining(
    current_matches_remaining: int,
    post_match_is_relevant: bool,
) -> int:
    """Decrement matches_remaining after a match is played (by post-match reactor).
    
    Called by the post-match reactor when a relevant competition match is completed.
    
    Args:
        current_matches_remaining: Current remaining match count
        post_match_is_relevant: True if the completed match is in the same competition
        
    Returns:
        Updated matches_remaining (decremented if relevant, unchanged otherwise)
    """
    if not post_match_is_relevant:
        # Match is in a different competition — don't decrement
        return current_matches_remaining
    
    if current_matches_remaining <= 0:
        # Already expired or non-positive — no further decrement
        return 0
    
    # Decrement
    return current_matches_remaining - 1


def is_active(
    matches_remaining: int,
    expires_after_match_id: Optional[str],
    resolved_match_id: Optional[str] = None,
) -> bool:
    """Check if a suspension is currently active (inverse of should_expire).
    
    Args:
        matches_remaining: Current remaining match count
        expires_after_match_id: Match ID after which suspension expires (or None)
        resolved_match_id: The ID of the most recently completed match (or None)
        
    Returns:
        True if suspension is active (not expired)
    """
    return not should_expire(matches_remaining, expires_after_match_id, resolved_match_id)


def get_expiration_reason(
    should_expire_bool: bool,
    matches_remaining: int,
    expires_after_match_id: Optional[str],
    resolved_match_id: Optional[str] = None,
) -> str:
    """Get a human-readable expiration reason.
    
    Args:
        should_expire_bool: Result of should_expire()
        matches_remaining: Current remaining match count
        expires_after_match_id: Match ID after which suspension expires (or None)
        resolved_match_id: The ID of the most recently completed match (or None)
        
    Returns:
        Human-readable explanation of expiration status
    """
    if not should_expire_bool:
        if matches_remaining > 0:
            return f"{matches_remaining} match(es) remaining"
        elif expires_after_match_id and not resolved_match_id:
            return f"Pending match resolution (after {expires_after_match_id})"
        else:
            return "Unknown status"
    
    return "Expired (matches_remaining=0 and trigger match resolved)"


__all__ = [
    "SuspensionState",
    "should_expire",
    "decrement_matches_remaining",
    "is_active",
    "get_expiration_reason",
]
