# Phase 13.23 — Fairness & bias detection

> Extracted from `docs/planning/ROADMAP.md` §13.23
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.23 Fairness & bias detection

> Retires assumption §13.0 #24. Ensures the predictor's errors are
> not systematically concentrated on certain teams, referees, or
> kickoff slots.

- [ ] **Per-segment residual audit.** Nightly `xops/leagues/bias_audit.py` computes residuals (predicted − realised) by `(team, referee, kickoff_slot, tier_mismatch_bucket)`; emits `proof.bias.v1` flags for segments where |residual| > `cfg.bias_residual_threshold` (default 0.10) over a rolling 90-day window.
- [ ] **Proofreader veto on systemic bias.** Phase 6 proofreader gains a per-league bias check; sustained bias on a segment vetoes T2→T1 promotion until investigated.
- [ ] **Referee-aware feature isolation.** If `referee_id` becomes a dominant predictor for one league (interaction effect > `cfg.referee_interaction_max`), feature is shrunk per `cfg.referee_shrinkage_lambda` to avoid leaking proxy bias (proof test `test_referee_shrinkage.py`).
- [ ] **Per-tier-mismatch fairness.** Domestic-cup early-round predictions (Süper Lig vs Lig 1) audit the predictor for systematic over-/under-confidence in upsets; separate metric `negelir_league_upset_calibration{league_id}`.
