# Phase 13.18 — Mid-season format/structure mutation

> Extracted from `docs/planning/ROADMAP.md` §13.18
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.18 Mid-season format/structure mutation

> Leagues do not always have constant composition: COVID-era expansion,
> mid-season club withdrawal (financial collapse), point deductions,
> expulsion, league-format changes (e.g. UCL 32 → 36 in 2024-25).
> Retires assumption §13.0 #19.

- [ ] **`LeagueSeason` Reference-plane entity.** `(league_id, season_id) → {teams[], format_overrides{}, point_deductions{team_id: pts}, expulsions[]}`; predictor reads the season's view, not the league's all-time view.
- [ ] **Format-override schema.** Mid-season changes (sub limit increase, knockout-stage expansion) live in `LeagueSeason.format_overrides` with `effective_from` UTC; changes propagate without code edits.
- [ ] **Point-deduction propagation.** Deductions affect the standings predictor and "to win league" derived market; raw match predictions (1X2) unaffected. Proof test `test_point_deduction_propagates_to_table_only.py`.
- [ ] **Withdrawal handling.** A team withdrawing mid-season triggers all its remaining fixtures to `cancelled` with `reason=team_withdrawal`; the resulting standings impact (3-0 awarded vs full annulment) follows the season's `withdrawal_policy` enum.
- [ ] **Calibration freeze.** Any mid-season mutation freezes the league's calibration profile for the remainder of the season (no live re-fit on a deformed corpus); profile resumes fitting from the next season's data. Proof test `test_calibration_frozen_after_format_mutation.py`.
- [ ] **Tracker + chart bump per mutation.** A `LeagueSeason` mutation forces a `make track.add` + `make version.bump COMPONENT=league_<id> LEVEL=patch`; lint-gated.
- [ ] **Concurrent-mutation safety.** Two ops applying mid-season mutations to the same `LeagueSeason` row simultaneously must serialise via per-league pessimistic lock (`pg_advisory_xact_lock` keyed on `hash(league_id, season_id)`); proof test `test_concurrent_season_mutation_serialised.py` runs 100 concurrent mutations and asserts no lost-update.
- [ ] **Mutation-replay determinism.** Replaying the audit-log mutation sequence onto a baseline `LeagueSeason` reproduces the current state byte-for-byte (proof test `test_season_mutation_replay_deterministic.py`); enables §13.42 time-travel for season views.
