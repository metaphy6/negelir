# Phase 13.53 — Cross-competition qualifier-flow plane

> Extracted from `docs/planning/ROADMAP.md` §13.53
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.53 Cross-competition qualifier-flow plane

> Retires assumption §13.0 #65. UCL group losers drop into the UEL
> knockout; UEL group losers drop into UECL playoff; Copa
> Libertadores eliminations feed Sudamericana. The flow must be
> declared, not inferred.

- [ ] **`QualifierFlow` Reference-plane entity.** `(flow_id, from_competition_id, from_stage_id, to_competition_id, to_stage_id, condition ∈ {winner, runner_up, third_place, drop_down, loser_of_round}, season_id)`.
- [ ] **Flow graph validation.** Loader builds a DAG; a cycle (`A → B → A` in same season) refuses load; proof test `test_qualifier_flow_no_cycles.py`.
- [ ] **Predictor consumption.** "Team X to win UEL" market reads the flow at draw time so it can include teams currently in the UCL group stage (with the conditional probability of being dropped); proof test `test_uel_winner_includes_ucl_drop_ins.py`.
- [ ] **Flow-mutation audit.** Adding/removing a flow is a §13.21 audit event + `make track.add` + chart bump per the affected competitions.
- [ ] **Cross-confederation flow.** A 13c flow (e.g. Copa Libertadores R16 loser → Sudamericana QF) follows the same schema; per §13.59 guest-team flows handled identically.
