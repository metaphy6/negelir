"""Phase 21.2 — Injury & availability extractor.

Parses Mackolik injury list and club presser fragments.
Produces InjuryPayload or AvailabilityPayload records; raises ExtractionError on invalid data.
Per ENRICHMENT_DATA.md §3.1 and AGENTS.md §2 (Rule 1: single-source config).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any, Dict, List
from urllib.parse import urlparse

from common.config import cfg
from common.logger import get_logger
from common.schemas.records import InjuryPayload, AvailabilityPayload

log = get_logger("scraper.extractors.injury_watch")


class ExtractionError(Exception):
    """Raised when data extraction fails (missing fields, format errors, etc.)."""

    def __init__(self, reason: str, payload: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.payload = payload
        super().__init__(f"ExtractionError: {reason}")


def _sha256_url_hash(canonical_url: str) -> str:
    """Compute SHA-256 hash of canonical URL without storing it.
    
    Per ENRICHMENT_DATA.md §3.1: source_url_hash is provenance fingerprint.
    """
    return hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()


@dataclass
class InjuryExtractor:
    """Extracts InjuryPayload and AvailabilityPayload from Mackolik + club presser.
    
    Per ENRICHMENT_DATA.md §3.2:
    - Sources: club sites (highest confidence), Mackolik injury list, editorial articles
    - Confidence: club_official > manager_presser > press > rumour (for availability)
    - All string fields are length-capped
    - Invalid rows raise ExtractionError
    """

    max_string_length: int = 500
    """Maximum length for string fields before truncation."""

    def _cap_string(self, value: str, field_name: str) -> str:
        """Cap string length and log if truncated."""
        if len(value) > self.max_string_length:
            log.warning(
                f"String field {field_name} truncated from {len(value)} to {self.max_string_length}"
            )
            return value[: self.max_string_length]
        return value

    def extract_injuries_from_mackolik_json(
        self, data: Dict[str, Any], source_url: str
    ) -> List[InjuryPayload]:
        """Extract injuries from Mackolik JSON API fragment.
        
        Expected structure:
        {
            "injuries": [
                {
                    "id": "INJ_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_1",
                    "body_part": "knee",
                    "severity": "moderate",
                    "diagnosed_at": "2026-06-20T10:30:00Z",
                    "expected_return": "2026-07-05",
                    "confidence": "press" | "club_statement"
                }
            ]
        }
        """
        results: List[InjuryPayload] = []
        source_hash = _sha256_url_hash(source_url)

        injuries = data.get("injuries", [])
        if not isinstance(injuries, list):
            raise ExtractionError("injuries field must be a list", data)

        for i, inj_data in enumerate(injuries):
            try:
                payload = self._parse_injury_record(inj_data, source_hash)
                results.append(payload)
            except ExtractionError as e:
                log.warning(
                    f"Failed to extract injury [{i}]: {e.reason}",
                    extra={"payload_excerpt": str(inj_data)[:200]},
                )
                raise

        return results

    def _parse_injury_record(
        self, inj_data: Dict[str, Any], source_hash: str
    ) -> InjuryPayload:
        """Parse and validate a single injury record."""
        required_fields = ["id", "player_id", "team_id", "body_part", "severity", "diagnosed_at", "confidence"]
        
        for field in required_fields:
            if field not in inj_data or inj_data[field] is None:
                raise ExtractionError(f"Missing required field: {field}", inj_data)

        severity = inj_data["severity"]
        if severity not in ("minor", "moderate", "major", "season_ending", "career_threat"):
            raise ExtractionError(f"Invalid severity: {severity}", inj_data)

        confidence = inj_data["confidence"]
        if confidence not in ("club_statement", "press", "rumour"):
            raise ExtractionError(f"Invalid confidence: {confidence}", inj_data)

        return InjuryPayload(
            injury_id=self._cap_string(str(inj_data["id"]), "injury_id"),
            player_id=self._cap_string(str(inj_data["player_id"]), "player_id"),
            team_id=self._cap_string(str(inj_data["team_id"]), "team_id"),
            body_part=self._cap_string(str(inj_data["body_part"]), "body_part"),
            severity=severity,  # type: ignore
            diagnosed_at=self._cap_string(str(inj_data["diagnosed_at"]), "diagnosed_at"),
            expected_return=self._cap_string(str(inj_data.get("expected_return", "")), "expected_return") or None,
            confidence=confidence,  # type: ignore
            source_url_hash=source_hash,
        )

    def extract_availability_from_presser_json(
        self, data: Dict[str, Any], source_url: str, confidence: str
    ) -> List[AvailabilityPayload]:
        """Extract availability from club presser or press fragments.
        
        Expected structure:
        {
            "availabilities": [
                {
                    "id": "AVAIL_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_1",
                    "fixture_id": null | "MATCH_123",
                    "status": "fit" | "doubtful" | "out" | "suspended" | "international_duty" | "rest",
                    "asserted_at": "2026-06-20T14:00:00Z"
                }
            ]
        }
        """
        results: List[AvailabilityPayload] = []

        if confidence not in ("club_official", "manager_presser", "press", "rumour"):
            raise ExtractionError(f"Invalid confidence: {confidence}")

        availabilities = data.get("availabilities", [])
        if not isinstance(availabilities, list):
            raise ExtractionError("availabilities field must be a list", data)

        for i, avail_data in enumerate(availabilities):
            try:
                payload = self._parse_availability_record(avail_data, confidence)
                results.append(payload)
            except ExtractionError as e:
                log.warning(
                    f"Failed to extract availability [{i}]: {e.reason}",
                    extra={"payload_excerpt": str(avail_data)[:200]},
                )
                raise

        return results

    def _parse_availability_record(
        self, avail_data: Dict[str, Any], source_confidence: str
    ) -> AvailabilityPayload:
        """Parse and validate a single availability record."""
        required_fields = ["id", "player_id", "team_id", "status", "asserted_at"]
        
        for field in required_fields:
            if field not in avail_data or avail_data[field] is None:
                raise ExtractionError(f"Missing required field: {field}", avail_data)

        status = avail_data["status"]
        valid_statuses = ("fit", "doubtful", "out", "suspended", "international_duty", "rest")
        if status not in valid_statuses:
            raise ExtractionError(f"Invalid status: {status}", avail_data)

        return AvailabilityPayload(
            availability_id=self._cap_string(str(avail_data["id"]), "availability_id"),
            player_id=self._cap_string(str(avail_data["player_id"]), "player_id"),
            team_id=self._cap_string(str(avail_data["team_id"]), "team_id"),
            fixture_id=str(avail_data.get("fixture_id", "")) if avail_data.get("fixture_id") else None,
            status=status,  # type: ignore
            asserted_at=self._cap_string(str(avail_data["asserted_at"]), "asserted_at"),
            source_confidence=source_confidence,  # type: ignore
        )

    def extract_from_mackolik_html(
        self, html: str, team_id: str, source_url: str
    ) -> List[InjuryPayload]:
        """Extract injuries from Mackolik HTML page (fallback).
        
        Looks for patterns like:
        - Injury tables with player name, body part, expected return
        - Structured data embedded in page
        """
        results: List[InjuryPayload] = []
        source_hash = _sha256_url_hash(source_url)
        
        # Regex pattern for injury row: "Player Name - Body Part - Return Date"
        pattern = r"<tr[^>]*>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?</tr>"
        
        matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
        injury_counter = 0
        
        for match in matches:
            player_name, body_part, expected_return = match.groups()
            player_name = player_name.strip()
            body_part = body_part.strip()
            expected_return = expected_return.strip()
            
            if not player_name:
                continue
            
            injury_counter += 1
            payload = InjuryPayload(
                injury_id=f"MACKOLIK_HTML_{team_id}_{injury_counter}",
                player_id=f"PLAYER_UNKNOWN_{player_name}",  # Will require enrichment step to resolve
                team_id=team_id,
                body_part=self._cap_string(body_part, "body_part"),
                severity="moderate",  # HTML doesn't always have severity; default to moderate
                diagnosed_at=datetime.utcnow().isoformat() + "Z",
                expected_return=expected_return if expected_return else None,
                confidence="press",  # HTML from Mackolik is "press" level
                source_url_hash=source_hash,
            )
            results.append(payload)
        
        return results
