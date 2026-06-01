# Phase 13.45 — Per-league market roster

> Extracted from `docs/planning/ROADMAP.md` §13.45
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.45 Per-league market roster

> Retires assumption §13.0 #52.

- [ ] **`LeagueRow.markets_supported: frozenset[market_id]`.** Each league declares which betting markets are valid for it (e.g. some leagues lack reliable corner-data and exclude `corners_over_under`).
- [ ] **Emitter refusal.** Phase 16 emitter refuses to publish a market not declared (proof test `test_emitter_refuses_undeclared_market.py`).
- [ ] **Proofreader veto.** Phase 6 proofreader vetoes a prediction whose market is not in the roster.
- [ ] **Per-format intersection.** Effective roster is `LeagueRow.markets_supported ∩ Competition.markets_supported_for_format` (e.g. "to qualify for next round" only on knockout).
- [ ] **Lint coverage.** `xops/lint/market_roster_coverage.py` asserts every market id mentioned in any extractor is declared in at least one `LeagueRow.markets_supported`; orphan markets fail CI.
- [ ] **Audit on roster mutation.** Adding / removing a market from a T1 league forces tracker row + chart bump per §13.21.
