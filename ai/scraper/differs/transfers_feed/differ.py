"""Phase 21.1 — Roster-state differ implementation.

Differs compare old vs. new enrichment payloads and emit DiffEvent objects
when fields change. Idempotent on re-fetch of identical data.

Per ROADMAP §21.1 and ENRICHMENT_DATA.md §2:
  - Transfer key: (player_id, effective_at, confidence) triple
  - Contract key: (player_id, team_id, contract_id)
  - Suspension key: (player_id, competition_id, suspension_id)

Differs emit a DiffEvent only when at least one field changes.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, TypedDict, Literal

from ai.common.schemas.records import (
    TransferPayload,
    ContractPayload,
    SuspensionPayload,
)
from ai.common.logger import get_logger

log = get_logger("scraper.differs.transfers_feed")


class DiffEvent(TypedDict):
    """Diff event emitted when a record changes.
    
    Per ROADMAP §21.1, DiffEvent contract:
      - source: str — source name (e.g. "mackolik")
      - entity_type: str — "transfer" | "contract" | "suspension"
      - key_tuple: tuple — the diff key
      - old_record: dict | None — old payload (None if created)
      - new_record: dict | None — new payload (None if deleted)
      - timestamp: str — ISO-8601 UTC when diff was detected
      - change_type: str — "created" | "updated" | "deleted"
    """
    source: str
    entity_type: str
    key_tuple: Tuple[Any, ...]
    old_record: Optional[Dict[str, Any]]
    new_record: Optional[Dict[str, Any]]
    timestamp: str
    change_type: Literal["created", "updated", "deleted"]


@dataclass
class BaseDiffer(ABC):
    """Abstract base class for enrichment differs.
    
    Subclasses define:
      - entity_type: str — type of entity (transfer/contract/suspension)
      - extract_key(record) -> tuple — diff key extraction
      - payload_to_dict(payload) -> dict — convert payload to dict
    """

    source: str = "unknown"
    """Source name for this differ (e.g. 'mackolik', 'club_site')."""

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """Entity type name (transfer/contract/suspension)."""
        pass

    @abstractmethod
    def extract_key(self, record: Optional[Dict[str, Any]]) -> Optional[Tuple[Any, ...]]:
        """Extract the diff key from a record.
        
        Returns None if the record is None (for deleted records).
        """
        pass

    @abstractmethod
    def payload_to_dict(self, payload: Any) -> Dict[str, Any]:
        """Convert payload to dict for comparison."""
        pass

    def compare(
        self,
        old_payload: Optional[Any],
        new_payload: Optional[Any],
    ) -> Optional[DiffEvent]:
        """Compare old and new payloads and emit DiffEvent if changed.
        
        Returns None if no change detected (idempotent).
        Raises ValueError if both payloads are None.
        """
        if old_payload is None and new_payload is None:
            raise ValueError("Both old_payload and new_payload cannot be None")

        # Convert payloads to dicts for comparison
        old_dict = self.payload_to_dict(old_payload) if old_payload else None
        new_dict = self.payload_to_dict(new_payload) if new_payload else None

        # Extract keys
        old_key = self.extract_key(old_dict)
        new_key = self.extract_key(new_dict)

        # Determine change type and whether to emit
        if old_dict is None and new_dict is not None:
            # Created: always emit
            change_type = "created"
            key_tuple = new_key
            should_emit = True
        elif old_dict is not None and new_dict is None:
            # Deleted: always emit
            change_type = "deleted"
            key_tuple = old_key
            should_emit = True
        elif old_dict is not None and new_dict is not None:
            # Updated: check if keys match and if fields changed
            if old_key != new_key:
                # Key changed — this is a structural change
                log.warning(
                    f"{self.entity_type} differ: key changed from {old_key} to {new_key}",
                    extra={"source": self.source},
                )
                # Treat as delete + create; emit only if we're checking for that
                change_type = "updated"
                key_tuple = new_key
                should_emit = True
            else:
                # Same key; check if any field changed
                if old_dict != new_dict:
                    change_type = "updated"
                    key_tuple = new_key
                    should_emit = True
                else:
                    # Identical; no diff
                    should_emit = False
                    change_type = "updated"
                    key_tuple = new_key
        else:
            raise ValueError("Unexpected state: both None (caught above)")

        if not should_emit:
            return None

        return DiffEvent(
            source=self.source,
            entity_type=self.entity_type,
            key_tuple=key_tuple,
            old_record=old_dict,
            new_record=new_dict,
            timestamp=datetime.now(timezone.utc).isoformat(),
            change_type=change_type,
        )


@dataclass
class TransferDiffer(BaseDiffer):
    """Differ for TransferPayload records.
    
    Diff key: (player_id, effective_at, confidence) triple
    Per ROADMAP §21.1:
      - Emits a diff event only when at least one field changes
      - Idempotent on re-fetch of identical data
    """

    @property
    def entity_type(self) -> str:
        return "transfer"

    def extract_key(
        self, record: Optional[Dict[str, Any]]
    ) -> Optional[Tuple[str, str, str]]:
        """Extract the diff key: (player_id, effective_at, confidence).
        
        Per ROADMAP §21.1: the triple uniquely identifies a transfer record.
        Returns None if record is None.
        """
        if record is None:
            return None
        return (
            record.get("player_id", ""),
            record.get("effective_at", ""),
            record.get("confidence", ""),
        )

    def payload_to_dict(self, payload: Optional[TransferPayload]) -> Dict[str, Any]:
        """Convert TransferPayload to dict."""
        if payload is None:
            return {}
        return dict(payload)  # type: ignore


@dataclass
class ContractDiffer(BaseDiffer):
    """Differ for ContractPayload records.
    
    Diff key: (player_id, team_id, contract_id)
    Per ENRICHMENT_DATA.md §2.1:
      - `extension` flag tracks contract updates vs. new contracts
      - Idempotent on re-fetch
    """

    @property
    def entity_type(self) -> str:
        return "contract"

    def extract_key(
        self, record: Optional[Dict[str, Any]]
    ) -> Optional[Tuple[str, str, str]]:
        """Extract the diff key: (player_id, team_id, contract_id).
        
        Returns None if record is None.
        """
        if record is None:
            return None
        return (
            record.get("player_id", ""),
            record.get("team_id", ""),
            record.get("contract_id", ""),
        )

    def payload_to_dict(
        self, payload: Optional[ContractPayload]
    ) -> Dict[str, Any]:
        """Convert ContractPayload to dict."""
        if payload is None:
            return {}
        return dict(payload)  # type: ignore


@dataclass
class SuspensionDiffer(BaseDiffer):
    """Differ for SuspensionPayload records.
    
    Diff key: (player_id, competition_id, suspension_id)
    Per ENRICHMENT_DATA.md §2.1:
      - `matches_remaining` decremented by post-match reactor
      - Record expires when `expires_after_match_id` resolves AND
        `matches_remaining` reaches 0
      - Idempotent on re-fetch
    """

    @property
    def entity_type(self) -> str:
        return "suspension"

    def extract_key(
        self, record: Optional[Dict[str, Any]]
    ) -> Optional[Tuple[str, str, str]]:
        """Extract the diff key: (player_id, competition_id, suspension_id).
        
        Returns None if record is None.
        """
        if record is None:
            return None
        return (
            record.get("player_id", ""),
            record.get("competition_id", ""),
            record.get("suspension_id", ""),
        )

    def payload_to_dict(
        self, payload: Optional[SuspensionPayload]
    ) -> Dict[str, Any]:
        """Convert SuspensionPayload to dict."""
        if payload is None:
            return {}
        return dict(payload)  # type: ignore
