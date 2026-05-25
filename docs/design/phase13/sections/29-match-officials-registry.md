# Phase 13.29 — Match-officials registry

> Extracted from `docs/planning/ROADMAP.md` §13.29
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.29 Match-officials registry

> Retires assumption §13.0 #36. The referee dimension is a real
> predictor input (foul rates, card rates, penalty rates) and a real
> bias-detection dimension (§13.23).

- [ ] **`Official` Reference-plane entity.** `(official_id, name, country, role_history[], appointment_history[])` keyed on `stable_id` (no per-source IDs leak); roles ∈ `{referee, ar1, ar2, fourth, var, avar, reserve_ar}`.
- [ ] **`FixtureOfficials` join table.** `(fixture_id, role, official_id, appointment_source, appointed_at)`; refuses two officials in the same role for the same fixture (proof test `test_no_duplicate_role_assignment.py`).
- [ ] **Appointment audit.** Every change to a fixture's officials emits `officials.assignment.v1{fixture_id, role, before, after, source, appointed_at}`; surfaces in the Phase 8 console.
- [ ] **Referee feature shrinkage.** Per §13.23, a referee's `card_rate_adj` / `penalty_rate_adj` / `foul_rate_adj` features are shrunk per `cfg.referee_shrinkage_lambda` toward the league mean until the official has worked ≥ `cfg.referee_min_matches_for_full_weight` (default 30) fixtures.
- [ ] **Cross-confederation referee identity.** A referee working in Süper Lig and UCL collapses to one `stable_id` via §13.4 anchor resolver; proof test `test_referee_cross_competition_identity.py`.
- [ ] **VAR-era guard.** Officials with `var` / `avar` roles only appear in fixtures whose competition has `var_active=true` at kickoff; lint + proof test `test_var_official_only_in_var_competition.py`.
- [ ] **Bias rotation tracking.** Per-official residual feeds §13.23; the bias-audit alert distinguishes referee bias from team / venue bias by partial regression.
