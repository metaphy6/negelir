"""Phase 21.1 — Roster-state extractors (transfers, contracts, suspensions).

Extracts TransferPayload, ContractPayload, and SuspensionPayload from:
  - Club website announcements (parsed via HTML/JSON markup)
  - Mackolik transfer feed (JSON API)

Per ENRICHMENT_DATA.md §2.2, sources include:
  - Official club announcements (TFF, club sites)
  - Mackolik transfer feed
  - (Transfermarkt-shaped data deferred to Phase 19 for licensing)

Discipline:
  - Invalid rows raise ExtractionError (never silently return None).
  - All string fields are length-capped before storage.
  - confidence field (rumour/agreed/official) is always present.
"""

from scraper.extractors.transfers_feed.extractor import (
    ContractExtractor,
    ExtractionError,
    SuspensionExtractor,
    TransferExtractor,
)

__all__ = [
    "TransferExtractor",
    "ContractExtractor",
    "SuspensionExtractor",
    "ExtractionError",
]
