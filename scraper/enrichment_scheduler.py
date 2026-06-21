"""Phase 21.1 §21.1 — Transfer-window scheduler for roster-state refresh.

Determines when to refresh roster-state (transfers, contracts, suspensions):
  - Daily cadence during transfer windows (Jul 1–Sep 1, Jan 1–Feb 1)
  - Weekly cadence outside windows
  - Per-confederation windows (stored in league catalog)
  - Emits heartbeat events for monitoring (even when no transfers found)

The scheduler is deterministic and testable. It does not hold state;
all decisions are based on the current date and confederation calendar.

Binding per ROADMAP §21.1 bullet 6 and ENRICHMENT_DATA.md §2.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional


def is_transfer_window(
    current_date: datetime,
    confederations_windows: dict[str, list[tuple[tuple[int, int], tuple[int, int]]]],
    confederation_id: str,
) -> bool:
    """Determine if a date is within a transfer window for a confederation.
    
    Args:
        current_date: Current date (UTC datetime)
        confederations_windows: Dict mapping confederation_id to list of window date ranges
                                E.g. {"UEFA": [((7, 1), (9, 1)), ((1, 1), (2, 1))]}
                                Format: tuple of ((start_month, start_day), (end_month, end_day))
        confederation_id: Confederation ID (e.g., "UEFA", "CONMEBOL")
        
    Returns:
        True if current_date falls within any transfer window for the confederation
    """
    if confederation_id not in confederations_windows:
        # Unknown confederation — assume outside window (weekly cadence)
        return False
    
    month = current_date.month
    day = current_date.day
    
    for (start_month, start_day), (end_month, end_day) in confederations_windows[confederation_id]:
        # Handle windows that span calendar years (e.g., Dec 20 – Jan 31)
        if start_month <= end_month:
            # Simple case: window does not cross year boundary
            if start_month < month < end_month:
                return True
            elif month == start_month and day >= start_day:
                return True
            elif month == end_month and day <= end_day:
                return True
        else:
            # Window crosses year boundary
            if month > start_month or month < end_month:
                return True
            elif month == start_month and day >= start_day:
                return True
            elif month == end_month and day <= end_day:
                return True
    
    return False


def get_cadence(
    current_date: datetime,
    confederations_windows: dict[str, list[tuple[tuple[int, int], tuple[int, int]]]],
    confederation_id: str,
) -> Literal["daily", "weekly"]:
    """Get the refresh cadence for a confederation on a given date.
    
    Args:
        current_date: Current date (UTC datetime)
        confederations_windows: Dict mapping confederation_id to list of window date ranges
        confederation_id: Confederation ID
        
    Returns:
        "daily" if in transfer window, "weekly" otherwise
    """
    if is_transfer_window(current_date, confederations_windows, confederation_id):
        return "daily"
    else:
        return "weekly"


def should_refresh(
    last_refresh_utc: Optional[str],
    current_date_utc: str,
    cadence: Literal["daily", "weekly"],
) -> bool:
    """Determine if a refresh should happen now based on last refresh and cadence.
    
    Args:
        last_refresh_utc: ISO-8601 UTC timestamp of last refresh (or None if never)
        current_date_utc: Current ISO-8601 UTC timestamp
        cadence: "daily" or "weekly"
        
    Returns:
        True if enough time has passed since last refresh
    """
    if last_refresh_utc is None:
        # Never refreshed — refresh now
        return True
    
    try:
        last_dt = datetime.fromisoformat(last_refresh_utc.replace('Z', '+00:00'))
        current_dt = datetime.fromisoformat(current_date_utc.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        # Invalid timestamp — refresh now (fail-open)
        return True
    
    elapsed_days = (current_dt - last_dt).days
    
    if cadence == "daily":
        return elapsed_days >= 1
    else:  # weekly
        return elapsed_days >= 7


def get_next_refresh_time(
    last_refresh_utc: Optional[str],
    cadence: Literal["daily", "weekly"],
    current_date_utc: str,
) -> str:
    """Calculate the next refresh time based on last refresh and cadence.
    
    Args:
        last_refresh_utc: ISO-8601 UTC timestamp of last refresh (or None)
        cadence: "daily" or "weekly"
        current_date_utc: Current ISO-8601 UTC timestamp
        
    Returns:
        ISO-8601 UTC timestamp of next scheduled refresh
    """
    if last_refresh_utc is None:
        # First refresh — return current time
        return current_date_utc
    
    try:
        last_dt = datetime.fromisoformat(last_refresh_utc.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return current_date_utc
    
    if cadence == "daily":
        # Next refresh is tomorrow at the same time
        from datetime import timedelta
        next_dt = last_dt + timedelta(days=1)
    else:  # weekly
        # Next refresh is 7 days from now
        from datetime import timedelta
        next_dt = last_dt + timedelta(days=7)
    
    return next_dt.isoformat().replace('+00:00', 'Z')


__all__ = [
    "is_transfer_window",
    "get_cadence",
    "should_refresh",
    "get_next_refresh_time",
]
