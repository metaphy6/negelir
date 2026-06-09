# Phase 13.51 — TBD-opponent placeholder fixtures

> Extracted from `docs/planning/ROADMAP.md` §13.51
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.51 TBD-opponent placeholder fixtures

> Retires assumption §13.0 #63. Cup draws often pre-publish bracket
> slots whose opponents are still TBD; predictor must surface
> partial markets without inventing a concrete fixture.

- [x] **`Fixture.opponent_placeholder` field.** Schema-level reference: `{role: "home"|"away", source_slot_id: "winner_of(quarter_final_3)"|"runner_up_of(group_b)", expected_resolution_by_utc}`; mutually exclusive with the corresponding `*_team_id` field.
- [x] **Predictor partial-market policy.** With one placeholder, predictor publishes `competition.qualify` and `competition.advance` markets (consume the bracket flow §13.53); refuses 1X2, BTTS, scoreline (proof test `test_placeholder_fixture_partial_markets.py`).
- [x] **Materialisation event.** `fixture.placeholder.resolved.v1{fixture_id, role, resolved_team_id}` triggers full re-prediction with `revision++`.
- [x] **Stale-placeholder watchdog.** A placeholder past `expected_resolution_by_utc + cfg.placeholder_stale_grace_h` (default 24 h) emits `proof.flag.v1{kind=placeholder_stale}` so ops chases the federation.
- [x] **No fabrication.** Lint refuses any code path that synthesises a synthetic team for a placeholder (doctrine #3).
