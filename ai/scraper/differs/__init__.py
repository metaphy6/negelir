"""Phase 21 — Enrichment differs.

Differs compare old vs. new enrichment payloads and emit DiffEvent objects
when fields change. They enforce idempotency: comparing the same pair of
records twice produces identical DiffEvent objects.

Per ENRICHMENT_DATA.md §2.2 and ROADMAP §21.1:
  - Transfer differ: key = (player_id, effective_at, confidence)
  - Contract differ: key = (player_id, team_id, contract_id)
  - Suspension differ: key = (player_id, competition_id, suspension_id)

Differs emit only when at least one field changes on re-fetch.
"""

__all__ = []
