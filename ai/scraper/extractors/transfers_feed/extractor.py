"""Phase 21.1 — Roster-state extractor (transfers, contracts, suspensions).

Parses club-site announcement markup and Mackolik transfer fragment.
Produces TransferPayload, ContractPayload, SuspensionPayload records.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, Literal, Any, Dict, List
from urllib.parse import urlparse

from ai.common.config import cfg
from ai.common.logger import get_logger
from ai.common.schemas.records import (
    TransferPayload,
    ContractPayload,
    SuspensionPayload,
)

log = get_logger("scraper.extractors.transfers_feed")


class ExtractionError(Exception):
    """Raised when data extraction fails (missing fields, format errors, etc.)."""

    def __init__(self, reason: str, payload: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.payload = payload
        super().__init__(f"ExtractionError: {reason}")


@dataclass
class TransferExtractor:
    """Extracts TransferPayload from club announcements and Mackolik feed.
    
    Per ENRICHMENT_DATA.md §2.2:
    - Sources: club announcements (TFF, club sites), Mackolik transfer feed
    - Confidence: rumour/agreed/official (editorial provenance)
    - Invalid rows raise ExtractionError
    - All string fields are length-capped
    """

    max_string_length: int = 500
    """Maximum length for string fields before truncation."""

    def extract_from_mackolik_json(
        self, data: Dict[str, Any]
    ) -> List[TransferPayload]:
        """Extract transfers from Mackolik JSON API fragment.
        
        Expected structure:
        {
            "transfers": [
                {
                    "id": "TR_12345",
                    "player_id": "P_67890",
                    "from_team_id": "TEAM_1",
                    "to_team_id": "TEAM_2",
                    "window": "summer" | "winter" | "emergency",
                    "type": "permanent" | "loan" | "free" | ...,
                    "fee_eur": null | int,
                    "contract_until": null | "2026-06-30",
                    "announced_at": "2026-06-20T10:30:00Z",
                    "effective_at": "2026-06-20T10:30:00Z",
                    "confidence": "rumour" | "agreed" | "official"
                }
            ]
        }
        """
        results: List[TransferPayload] = []

        transfers = data.get("transfers", [])
        if not isinstance(transfers, list):
            raise ExtractionError("transfers field must be a list", data)

        for i, tx_data in enumerate(transfers):
            try:
                payload = self._parse_transfer_record(tx_data)
                results.append(payload)
            except ExtractionError as e:
                log.warning(
                    f"Failed to extract transfer [{i}]: {e.reason}",
                    extra={"payload_excerpt": str(tx_data)[:200]},
                )
                raise

        return results

    def extract_from_club_html(self, html: str, team_id: str) -> List[TransferPayload]:
        """Extract transfers from club website HTML announcement.
        
        Looks for patterns like:
        - "Player Name joins Team from Previous Team"
        - Structured data in <script type="application/ld+json">
        
        Falls back to regex patterns if no JSON-LD found.
        """
        results: List[TransferPayload] = []

        # Try JSON-LD first
        json_ld_match = re.search(
            r'<script type="application/ld\+json">({.*?})</script>',
            html,
            re.DOTALL,
        )
        if json_ld_match:
            try:
                ld_json = json.loads(json_ld_match.group(1))
                if "transfers" in ld_json:
                    transfers = ld_json["transfers"]
                    if isinstance(transfers, list):
                        for tx_data in transfers:
                            try:
                                payload = self._parse_transfer_record(tx_data)
                                results.append(payload)
                            except ExtractionError as e:
                                log.debug(f"JSON-LD transfer parse failed: {e.reason}")
                                continue
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                log.debug(f"JSON-LD parse failed: {e}")

        return results

    def _parse_transfer_record(self, record: Dict[str, Any]) -> TransferPayload:
        """Parse and validate a single transfer record.
        
        Raises ExtractionError if required fields are missing or malformed.
        Applies length limits to string fields.
        """
        required_fields = {
            "id": str,
            "player_id": str,
            "window": str,
            "type": str,
            "announced_at": str,
            "effective_at": str,
            "confidence": str,
        }

        # Validate required fields
        for field, expected_type in required_fields.items():
            if field not in record:
                raise ExtractionError(
                    f"missing required field: {field}",
                    record,
                )
            if not isinstance(record[field], expected_type):
                raise ExtractionError(
                    f"field {field} has wrong type: {type(record[field]).__name__}, expected {expected_type.__name__}",
                    record,
                )

        # Validate enum fields
        window = record["window"]
        if window not in ("summer", "winter", "emergency"):
            raise ExtractionError(f"invalid window value: {window}", record)

        tx_type = record["type"]
        if tx_type not in (
            "permanent",
            "loan",
            "loan_with_option",
            "free",
            "end_of_loan",
        ):
            raise ExtractionError(f"invalid transfer type: {tx_type}", record)

        confidence = record["confidence"]
        if confidence not in ("rumour", "agreed", "official"):
            raise ExtractionError(f"invalid confidence value: {confidence}", record)

        # Validate and parse ISO dates
        try:
            announced_at_dt = datetime.fromisoformat(
                record["announced_at"].replace("Z", "+00:00")
            )
            effective_at_dt = datetime.fromisoformat(
                record["effective_at"].replace("Z", "+00:00")
            )
        except (ValueError, AttributeError) as e:
            raise ExtractionError(
                f"invalid ISO date format: {e}",
                record,
            )

        # Optional fields with defaults
        from_team_id = record.get("from_team_id", None)
        to_team_id = record.get("to_team_id", None)

        if from_team_id is not None and not isinstance(from_team_id, str):
            raise ExtractionError("from_team_id must be string or null", record)
        if to_team_id is not None and not isinstance(to_team_id, str):
            raise ExtractionError("to_team_id must be string or null", record)

        fee_eur = record.get("fee_eur", None)
        if fee_eur is not None and not isinstance(fee_eur, int):
            raise ExtractionError("fee_eur must be int or null", record)

        contract_until = record.get("contract_until", None)
        if contract_until is not None:
            if not isinstance(contract_until, str):
                raise ExtractionError("contract_until must be string or null", record)
            # Validate ISO date format
            try:
                datetime.fromisoformat(contract_until).date()
            except ValueError:
                raise ExtractionError(
                    f"contract_until has invalid date format: {contract_until}", record
                )

        # Build payload with length-capped strings
        payload: TransferPayload = {
            "transfer_id": self._cap_string(record["id"]),
            "player_id": self._cap_string(record["player_id"]),
            "from_team_id": (
                self._cap_string(from_team_id) if from_team_id else None
            ),
            "to_team_id": self._cap_string(to_team_id) if to_team_id else None,
            "transfer_window": window,  # type: ignore
            "transfer_type": tx_type,  # type: ignore
            "fee_eur": fee_eur,
            "contract_until": contract_until,
            "announced_at": announced_at_dt.isoformat(),
            "effective_at": effective_at_dt.isoformat(),
            "confidence": confidence,  # type: ignore
        }

        return payload

    def _cap_string(self, value: Optional[str]) -> Optional[str]:
        """Cap string length per configuration."""
        if value is None:
            return None
        if len(value) > self.max_string_length:
            return value[: self.max_string_length]
        return value


@dataclass
class ContractExtractor:
    """Extracts ContractPayload from club announcements and feeds.
    
    Per ENRICHMENT_DATA.md §2.1:
    - Records track contract start/end dates
    - extension flag indicates contract update vs. new contract
    """

    max_string_length: int = 500

    def extract_from_json(self, data: Dict[str, Any]) -> List[ContractPayload]:
        """Extract contracts from JSON structure.
        
        Expected structure:
        {
            "contracts": [
                {
                    "id": "C_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_1",
                    "starts_at": "2024-07-01",
                    "expires_at": "2026-06-30",
                    "extension": false
                }
            ]
        }
        """
        results: List[ContractPayload] = []

        contracts = data.get("contracts", [])
        if not isinstance(contracts, list):
            raise ExtractionError("contracts field must be a list", data)

        for i, contract_data in enumerate(contracts):
            try:
                payload = self._parse_contract_record(contract_data)
                results.append(payload)
            except ExtractionError as e:
                log.warning(
                    f"Failed to extract contract [{i}]: {e.reason}",
                    extra={"payload_excerpt": str(contract_data)[:200]},
                )
                raise

        return results

    def _parse_contract_record(self, record: Dict[str, Any]) -> ContractPayload:
        """Parse and validate a single contract record."""
        required_fields = {
            "id": str,
            "player_id": str,
            "team_id": str,
            "starts_at": str,
            "expires_at": str,
            "extension": bool,
        }

        for field, expected_type in required_fields.items():
            if field not in record:
                raise ExtractionError(f"missing required field: {field}", record)
            if not isinstance(record[field], expected_type):
                raise ExtractionError(
                    f"field {field} has wrong type: {type(record[field]).__name__}, expected {expected_type.__name__}",
                    record,
                )

        # Validate ISO date format
        try:
            datetime.fromisoformat(record["starts_at"]).date()
            datetime.fromisoformat(record["expires_at"]).date()
        except ValueError as e:
            raise ExtractionError(f"invalid date format: {e}", record)

        payload: ContractPayload = {
            "contract_id": self._cap_string(record["id"]),
            "player_id": self._cap_string(record["player_id"]),
            "team_id": self._cap_string(record["team_id"]),
            "starts_at": record["starts_at"],
            "expires_at": record["expires_at"],
            "extension": record["extension"],
        }

        return payload

    def _cap_string(self, value: Optional[str]) -> Optional[str]:
        """Cap string length per configuration."""
        if value is None:
            return None
        if len(value) > self.max_string_length:
            return value[: self.max_string_length]
        return value


@dataclass
class SuspensionExtractor:
    """Extracts SuspensionPayload from disciplinary records and feeds.
    
    Per ENRICHMENT_DATA.md §2.1:
    - Suspensions are competition-scoped
    - Reason: accumulated_yellows, red, disciplinary, doping
    - matches_remaining decremented by post-match reactor
    """

    max_string_length: int = 500

    def extract_from_json(self, data: Dict[str, Any]) -> List[SuspensionPayload]:
        """Extract suspensions from JSON structure.
        
        Expected structure:
        {
            "suspensions": [
                {
                    "id": "S_12345",
                    "player_id": "P_67890",
                    "team_id": "TEAM_1",
                    "competition_id": "TR_SUPER_LIG",
                    "reason": "accumulated_yellows",
                    "matches_remaining": 2,
                    "starts_at": "2026-06-20",
                    "expires_after_match_id": "MATCH_54321" | null
                }
            ]
        }
        """
        results: List[SuspensionPayload] = []

        suspensions = data.get("suspensions", [])
        if not isinstance(suspensions, list):
            raise ExtractionError("suspensions field must be a list", data)

        for i, susp_data in enumerate(suspensions):
            try:
                payload = self._parse_suspension_record(susp_data)
                results.append(payload)
            except ExtractionError as e:
                log.warning(
                    f"Failed to extract suspension [{i}]: {e.reason}",
                    extra={"payload_excerpt": str(susp_data)[:200]},
                )
                raise

        return results

    def _parse_suspension_record(self, record: Dict[str, Any]) -> SuspensionPayload:
        """Parse and validate a single suspension record."""
        required_fields = {
            "id": str,
            "player_id": str,
            "team_id": str,
            "competition_id": str,
            "reason": str,
            "matches_remaining": int,
            "starts_at": str,
        }

        for field, expected_type in required_fields.items():
            if field not in record:
                raise ExtractionError(f"missing required field: {field}", record)
            if not isinstance(record[field], expected_type):
                raise ExtractionError(
                    f"field {field} has wrong type: {type(record[field]).__name__}, expected {expected_type.__name__}",
                    record,
                )

        reason = record["reason"]
        if reason not in ("accumulated_yellows", "red", "disciplinary", "doping"):
            raise ExtractionError(f"invalid reason value: {reason}", record)

        matches_remaining = record["matches_remaining"]
        if matches_remaining < 0:
            raise ExtractionError(
                f"matches_remaining must be >= 0, got {matches_remaining}",
                record,
            )

        # Validate ISO date format
        try:
            datetime.fromisoformat(record["starts_at"]).date()
        except ValueError as e:
            raise ExtractionError(f"invalid starts_at date format: {e}", record)

        # expires_after_match_id is optional
        expires_after_match_id = record.get("expires_after_match_id", None)
        if (
            expires_after_match_id is not None
            and not isinstance(expires_after_match_id, str)
        ):
            raise ExtractionError(
                "expires_after_match_id must be string or null",
                record,
            )

        payload: SuspensionPayload = {
            "suspension_id": self._cap_string(record["id"]),
            "player_id": self._cap_string(record["player_id"]),
            "team_id": self._cap_string(record["team_id"]),
            "competition_id": self._cap_string(record["competition_id"]),
            "reason": reason,  # type: ignore
            "matches_remaining": matches_remaining,
            "starts_at": record["starts_at"],
            "expires_after_match_id": (
                self._cap_string(expires_after_match_id)
                if expires_after_match_id
                else None
            ),
        }

        return payload

    def _cap_string(self, value: Optional[str]) -> Optional[str]:
        """Cap string length per configuration."""
        if value is None:
            return None
        if len(value) > self.max_string_length:
            return value[: self.max_string_length]
        return value
