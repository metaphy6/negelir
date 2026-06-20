"""Phase 21.1 — Roster-state differs (transfers, contracts, suspensions).

Differs compare old vs. new payloads and emit DiffEvent objects when
fields change. Idempotent: identical re-fetches produce no diff.

Per ROADMAP §21.1:
  - Transfer key: (player_id, effective_at, confidence)
  - Contract key: (player_id, team_id, contract_id)
  - Suspension key: (player_id, competition_id, suspension_id)

DiffEvent contract:
  - source: str (source name, e.g. "mackolik")
  - entity_type: str ("transfer" | "contract" | "suspension")
  - key_tuple: tuple (diff key)
  - old_record: dict | None (old payload, None if new record)
  - new_record: dict | None (new payload, None if deleted record)
  - timestamp: str (ISO-8601 UTC when diff was detected)
  - change_type: str ("created" | "updated" | "deleted")

Confidence gate contract (bullet 4):
  - rumour → editorial-plane sentiment only; no roster-state write
  - agreed → provisional roster-state write; provisional=true flag
  - official → final roster-state write; clear provisional on same player
"""

from ai.scraper.differs.transfers_feed.differ import (
    BaseDiffer,
    TransferDiffer,
    ContractDiffer,
    SuspensionDiffer,
    DiffEvent,
)

from ai.scraper.differs.transfers_feed.confidence_gate import (
    RosterStateWriteInstruction,
    should_write,
    get_write_mode,
    apply_gate,
)

__all__ = [
    "BaseDiffer",
    "TransferDiffer",
    "ContractDiffer",
    "SuspensionDiffer",
    "DiffEvent",
    "RosterStateWriteInstruction",
    "should_write",
    "get_write_mode",
    "apply_gate",
]
