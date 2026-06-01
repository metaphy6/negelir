# Phase 13.56 — Per-season market roster overlay

> Extracted from `docs/planning/ROADMAP.md` §13.56
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.56 Per-season market roster overlay

> Retires assumption §13.0 #68. Market rosters change between
> seasons (Süper Lig added Asian Handicap from 2022-23; Premier
> League added "Goalscorer Method" market 2024-25).

- [ ] **`LeagueSeason.markets_supported_overrides: {add: frozenset[market_id], remove: frozenset[market_id]}`.** Effective roster for a season = `LeagueRow.markets_supported ∪ overrides.add - overrides.remove`.
- [ ] **Per-season effective roster cache.** Computed once per `(league_id, season_id)`; cache invalidated on §13.26 reload; cache hit ratio tracked via `negelir_market_roster_cache_hit_ratio`.
- [ ] **Predictor consumes season roster, not catalog default.** Proof test `test_predictor_uses_season_roster.py` (publishes for 2022-23 fixture confirms Asian Handicap accepted; 2021-22 fixture confirms refused).
- [ ] **Audit on override mutation.** Per §13.21; tracker row + chart bump for the affected league.
- [ ] **Cross-reference with §13.45.** Effective roster is the intersection of season override × format roster × per-format intersection.
