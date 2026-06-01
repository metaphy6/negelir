# Phase 13.40 — Cascade-postponement & withdrawal reactor

> Extracted from `docs/planning/ROADMAP.md` §13.40
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.40 Cascade-postponement & withdrawal reactor

> Retires assumption §13.0 #47.

- [ ] **`swarm/proofreader/cascade_reactor.py`.** Consumes `fixture.lifecycle.v1`; computes the dependent set (group standings, knockout-bracket placeholders, tie legs); emits one transactional `cascade.invalidated.v1{fixture_ids[], standings_delta, tie_ids[]}`.
- [ ] **Withdrawal cascade-set computation.** A team's withdrawal generates the deterministic full set of affected fixtures; `withdrawal_policy ∈ {annul_all_results, void_remaining_award_3_0, void_remaining_award_0_0}` per §13.18 chosen per league rule.
- [ ] **Cycle detection.** Reactor refuses to process a cascade whose dependency graph has a cycle (would only happen on bad data); audit + alert.
- [ ] **Idempotency.** Re-running the cascade reactor on the same input is a no-op (proof test `test_cascade_reactor_idempotent.py`).
- [ ] **Standings re-derivation determinism.** `make leagues.standings.recompute LEAGUE=<id> SEASON=<id>` is byte-identical across two runs given the same fixture history (proof test `test_standings_recompute_deterministic.py`).
- [ ] **Audit topic.** `cascade.fan_out.v1{trigger_fixture_id, dependent_count, computed_at}` consumed by the Phase 8 console.

#### 13.40.5 Retroactive-sanction reactor

> Retires assumption §13.0 #59.

- [ ] **Retroactive-event payload.** `RetroactiveSanction(target_id, kind ∈ {expulsion, point_deduction, forfeit, replay_ordered}, effective_kickoff_ts, retroactive_at, reason, source_authority)`.
- [ ] **No raw-fixture rewrite.** Retroactive sanctions feed the standings re-derivation only; raw `Fixture` records are never modified (proof test `test_retroactive_no_fixture_rewrite.py`).
- [ ] **Replay-ordered handling.** A federation-ordered replay creates a new fixture linked via `original_fixture_id`; predictor publishes a fresh prediction.
- [ ] **Standings monotonicity in display.** Frontend renders both the "as-played" and "after-sanction" tables when divergent; predictor's "to win league" market reads the after-sanction view.
