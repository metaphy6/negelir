"""Phase 21.3 — Referee assignment extractor.

Parses TFF referee assignment pages and UEFA/FIFA feeds.
Produces RefereeAssignmentPayload records; validates referee IDs; raises ExtractionError on invalid data.
Per ENRICHMENT_DATA.md §4.2 and AGENTS.md §2 (Rule 1: single-source config).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List, Set
import logging

from ai.common.config import cfg
from ai.common.logger import get_logger
from ai.common.schemas.records import RefereeAssignmentPayload

log = get_logger("scraper.extractors.referee_watch")


class ExtractionError(Exception):
    """Raised when referee data extraction fails."""

    def __init__(self, reason: str, payload: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.payload = payload
        super().__init__(f"ExtractionError: {reason}")


@dataclass
class RefereeExtractor:
    """Extracts RefereeAssignmentPayload from TFF pages and UEFA/FIFA feeds.
    
    Per ENRICHMENT_DATA.md §4.2:
    - Sources: TFF for TR matches, UEFA for European competitions, FIFA for international
    - Assignment: 1-3 days pre-KO from federation/UEFA/FIFA
    - Validates main_referee_id against known referee profiles; raises ExtractionError if unknown
    """

    known_referee_ids: Set[str] | None = None
    """Cache of known referee IDs; loaded from db on first extraction if None."""

    max_name_length: int = 200
    """Maximum length for name fields."""

    def _load_known_referees_from_db(self) -> Set[str]:
        """Load known referee IDs from the referee_profiles table.
        
        Called once per extractor instance if known_referee_ids is None.
        Returns empty set if table doesn't exist or db unavailable (allows bootstrap).
        """
        try:
            from common.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT referee_id FROM referee_profiles LIMIT 10000;"
            )
            rows = cursor.fetchall()
            ids = {row[0] for row in rows}
            log.debug(f"Loaded {len(ids)} known referee IDs from database")
            return ids
        except Exception as e:
            log.warning(f"Could not load known referees from db: {e}; allowing bootstrap")
            return set()

    def _validate_referee_id(self, referee_id: str, fixture_id: str) -> None:
        """Validate that referee_id exists in known_referee_ids.
        
        Raises ExtractionError if unknown and not in bootstrap mode.
        """
        if self.known_referee_ids is None:
            self.known_referee_ids = self._load_known_referees_from_db()

        # During bootstrap (empty profiles table), allow any valid UUID-like ID
        if not self.known_referee_ids:
            log.debug(f"Bootstrap mode: accepting referee {referee_id} without validation")
            return

        # Normal mode: validate referee exists
        if referee_id not in self.known_referee_ids:
            raise ExtractionError(
                f"Unknown referee_id '{referee_id}' for fixture '{fixture_id}'",
                {"fixture_id": fixture_id, "referee_id": referee_id}
            )

    def _cap_string(self, value: str, field_name: str) -> str:
        """Cap string length and log if truncated."""
        if len(value) > self.max_name_length:
            log.warning(
                f"String field {field_name} truncated from {len(value)} to {self.max_name_length}"
            )
            return value[: self.max_name_length]
        return value

    def _is_last_minute_change(
        self, announced_at: str, fixture_kickoff: str
    ) -> bool:
        """Determine if assignment is a last-minute change (< 24h pre-KO).
        
        Both times must be ISO-8601 UTC format.
        """
        try:
            announced = datetime.fromisoformat(announced_at.replace("Z", "+00:00"))
            kickoff = datetime.fromisoformat(fixture_kickoff.replace("Z", "+00:00"))
            hours_before_ko = (kickoff - announced).total_seconds() / 3600
            return 0 < hours_before_ko < 24
        except (ValueError, TypeError):
            log.warning(f"Could not parse times for last_minute_change: {announced_at} vs {fixture_kickoff}")
            return False

    def extract_assignment(
        self,
        assignment_id: str,
        fixture_id: str,
        main_referee_id: str,
        assistant_ids: List[str],
        fourth_official_id: Optional[str],
        var_referee_id: Optional[str],
        avar_referee_id: Optional[str],
        announced_at: str,
        fixture_kickoff: Optional[str] = None,
    ) -> RefereeAssignmentPayload:
        """Extract a single RefereeAssignmentPayload record.
        
        Args:
            assignment_id: Unique ID for this assignment.
            fixture_id: Match fixture ID.
            main_referee_id: Main referee ID (validated against known profiles).
            assistant_ids: List of assistant referee IDs.
            fourth_official_id: Fourth official ID, if present.
            var_referee_id: VAR referee ID, if present.
            avar_referee_id: Assistant VAR ID, if present.
            announced_at: ISO-8601 UTC when assignment was announced.
            fixture_kickoff: ISO-8601 UTC fixture kickoff (needed for last_minute_change detection).

        Returns:
            RefereeAssignmentPayload

        Raises:
            ExtractionError: If main_referee_id is unknown or data validation fails.
        """
        # Validate main referee
        self._validate_referee_id(main_referee_id, fixture_id)

        # Determine last-minute change flag
        last_minute_change = False
        if fixture_kickoff:
            last_minute_change = self._is_last_minute_change(announced_at, fixture_kickoff)

        payload: RefereeAssignmentPayload = {
            "assignment_id": assignment_id,
            "fixture_id": fixture_id,
            "main_referee_id": main_referee_id,
            "assistant_referee_ids": assistant_ids or [],
            "fourth_official_id": fourth_official_id,
            "var_referee_id": var_referee_id,
            "avar_referee_id": avar_referee_id,
            "announced_at": announced_at,
            "last_minute_change": last_minute_change,
        }

        return payload

    def extract_from_tff_json(
        self, data: Dict[str, Any], fixture_id: str, fixture_kickoff: Optional[str] = None
    ) -> RefereeAssignmentPayload:
        """Extract assignment from TFF JSON structure.
        
        Expected structure:
        {
            "assignment_id": "ASSIGN_12345",
            "main_referee": {
                "referee_id": "REF_1001",
            },
            "assistants": [
                {"referee_id": "REF_1002"},
                {"referee_id": "REF_1003"}
            ],
            "fourth_official": {"referee_id": "REF_1004"} | null,
            "var_referee": {"referee_id": "REF_1005"} | null,
            "avar_referee": {"referee_id": "REF_1006"} | null,
            "announced_at": "2026-06-20T10:00:00Z"
        }
        """
        try:
            assignment_id = data.get("assignment_id")
            announced_at = data.get("announced_at")

            if not assignment_id:
                raise ExtractionError("Missing assignment_id", data)
            if not announced_at:
                raise ExtractionError("Missing announced_at", data)

            main_ref = data.get("main_referee", {})
            main_referee_id = main_ref.get("referee_id")
            if not main_referee_id:
                raise ExtractionError("Missing main_referee.referee_id", data)

            assistant_ids = []
            for asst in data.get("assistants", []):
                asst_id = asst.get("referee_id")
                if asst_id:
                    assistant_ids.append(asst_id)

            fourth_off = data.get("fourth_official")
            fourth_official_id = fourth_off.get("referee_id") if fourth_off else None

            var_ref = data.get("var_referee")
            var_referee_id = var_ref.get("referee_id") if var_ref else None

            avar_ref = data.get("avar_referee")
            avar_referee_id = avar_ref.get("referee_id") if avar_ref else None

            return self.extract_assignment(
                assignment_id=assignment_id,
                fixture_id=fixture_id,
                main_referee_id=main_referee_id,
                assistant_ids=assistant_ids,
                fourth_official_id=fourth_official_id,
                var_referee_id=var_referee_id,
                avar_referee_id=avar_referee_id,
                announced_at=announced_at,
                fixture_kickoff=fixture_kickoff,
            )

        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Unexpected error parsing TFF JSON: {e}", data)
