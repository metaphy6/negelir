# Phase 13.41 — League rebrand & display-name handover

> Extracted from `docs/planning/ROADMAP.md` §13.41
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.41 League rebrand & display-name handover

> Retires assumption §13.0 #48.

- [x] **`LeagueRow.legal_name`, `LeagueRow.display_name`, `LeagueRow.aliases`.** `league_id` is the join key and never changes; `legal_name` and `display_name` mutate via signed audit per §13.21.
- [x] **`make leagues.rename LEAGUE=<id> DISPLAY=<new> REASON=""`** writes the audit + tracker row + chart-bump (per §13.21 / §13.27); refuses to mutate `league_id`.
- [x] **Search alias propagation.** Old `display_name` is auto-added to `aliases[]` so historical queries still resolve; gazetteer (§13.11) auto-feeds.
- [x] **Country-split / merger drill.** Yugoslav-style federation split → multiple new `league_id` rows seeded from the dissolved league's history (manual mapping audited); proof test `test_federation_split_audit_trail.py`.
- [x] **API stability.** `/v1/catalog` returns both `legal_name` and `display_name`; clients are expected to render `display_name`.
