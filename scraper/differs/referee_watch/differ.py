"""Phase 21.3 — Referee assignment differ.

Detects changes in referee assignments via diff key (fixture_id, main_referee_id).
Handles last-minute changes (< 24h pre-KO), deduplication, and reassignment tracking.
Per ENRICHMENT_DATA.md §4.4 and CONTENT_FRESHNESS.md §7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
import logging

from common.config import cfg
from common.logger import get_logger
from common.schemas.records import RefereeAssignmentPayload

log = get_logger("scraper.differs.referee_watch")


@dataclass
class RefereeDiffer:
    """Differs RefereeAssignmentPayload records.
    
    Diff key: (fixture_id, main_referee_id)
    
    Per ENRICHMENT_DATA.md §4.4:
    - last_minute_change is set to true when a reassignment arrives < 24h pre-KO
    - 5-min writer-side deduplication window: (fixture_id, main_referee_id, announced_at)
    - Duplicate assignments treated as updates (last-write-wins)
    - A reassignment from ref A to ref B within 5 min is still last_minute_change=true if
      the gap between original announced_at and new announced_at is < 24h
    """
    
    dedup_window_s: int = field(default_factory=lambda: 300)
    """Writer-side deduplication window (default 5 min)."""

    def diff_key(self, payload: RefereeAssignmentPayload) -> Tuple[str, str]:
        """Compute diff key for a referee assignment.
        
        Per spec: (fixture_id, main_referee_id)
        """
        return (payload["fixture_id"], payload["main_referee_id"])

    def is_duplicate_within_dedup_window(
        self,
        new_payload: RefereeAssignmentPayload,
        prev_payload: Optional[RefereeAssignmentPayload],
        current_time: Optional[datetime] = None,
    ) -> bool:
        """Check if new_payload is a duplicate of prev_payload within dedup window.
        
        Dedup key: (fixture_id, main_referee_id, announced_at)
        Only the announced_at timestamp is checked within the window; exact match required.
        
        Args:
            new_payload: New assignment record.
            prev_payload: Previous assignment record (None if this is first).
            current_time: Current time for dedup window check (defaults to now UTC).

        Returns:
            True if duplicate within window; False otherwise.
        """
        if prev_payload is None:
            return False

        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Parse announced_at times
        try:
            new_announced = datetime.fromisoformat(
                new_payload["announced_at"].replace("Z", "+00:00")
            )
            prev_announced = datetime.fromisoformat(
                prev_payload["announced_at"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError) as e:
            log.warning(f"Could not parse announced_at times for dedup: {e}")
            return False

        # Check if previous write is within dedup window
        time_since_prev = (current_time - prev_announced).total_seconds()
        if time_since_prev > self.dedup_window_s:
            return False

        # Check if announced_at matches exactly (same announcement)
        return new_announced == prev_announced

    def should_emit_last_minute_change(
        self,
        new_payload: RefereeAssignmentPayload,
        prev_payload: Optional[RefereeAssignmentPayload],
    ) -> bool:
        """Determine if a reassignment is a genuine last-minute change.
        
        A reassignment from ref A to ref B that arrives within 5 min of the previous write
        is still a last_minute_change=true event if the gap between the original announced_at
        and the new announced_at is < 24h.
        
        Per ENRICHMENT_DATA.md §4.4:
        - 5-min writer window: prevents burst duplicates within a single scrape cycle
        - 24h window: detects genuine last-minute reassignments between scrape cycles
        """
        # If there's no previous assignment, this is not a reassignment
        if prev_payload is None:
            return new_payload.get("last_minute_change", False)

        # Check if main referee changed (reassignment)
        if new_payload["main_referee_id"] == prev_payload["main_referee_id"]:
            return False

        # Referee changed: check if gap between announced times is < 24h
        try:
            prev_announced = datetime.fromisoformat(
                prev_payload["announced_at"].replace("Z", "+00:00")
            )
            new_announced = datetime.fromisoformat(
                new_payload["announced_at"].replace("Z", "+00:00")
            )
            gap_hours = (new_announced - prev_announced).total_seconds() / 3600
            is_last_minute = 0 < gap_hours < 24

            if is_last_minute:
                log.info(
                    f"Detected last-minute reassignment for fixture {new_payload['fixture_id']}: "
                    f"{prev_payload['main_referee_id']} → {new_payload['main_referee_id']} "
                    f"({gap_hours:.1f}h gap)"
                )

            return is_last_minute
        except (ValueError, TypeError) as e:
            log.warning(f"Could not parse announced times for reassignment detection: {e}")
            return False

    def process_change(
        self,
        new_payload: RefereeAssignmentPayload,
        prev_payload: Optional[RefereeAssignmentPayload],
    ) -> Dict[str, Any]:
        """Process a referee assignment change.
        
        Returns a dict with:
        - is_duplicate: bool
        - is_update: bool (reassignment from previous referee)
        - is_last_minute: bool
        - change_type: str ("new" | "update" | "duplicate")
        """
        is_duplicate = self.is_duplicate_within_dedup_window(new_payload, prev_payload)

        if is_duplicate:
            log.debug(
                f"Duplicate assignment for fixture {new_payload['fixture_id']} "
                f"within dedup window; ignoring"
            )
            return {
                "is_duplicate": True,
                "is_update": False,
                "is_last_minute": False,
                "change_type": "duplicate",
            }

        is_update = prev_payload is not None
        is_last_minute = self.should_emit_last_minute_change(new_payload, prev_payload)

        change_type = "new" if not is_update else "update"

        return {
            "is_duplicate": False,
            "is_update": is_update,
            "is_last_minute": is_last_minute,
            "change_type": change_type,
        }
