# Phase 13.5 — Calibration backfill & per-format backtest harness

> Extracted from `docs/planning/ROADMAP.md` §13.5
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.5 Calibration backfill & per-format backtest harness

- [ ] **Per-competition backtest corpus.** For every active competition, ≥ 2 full editions of historical results in the Reference + Schedule + Live planes; gap report fails the readiness gate (LEAGUE_CATALOG §2.1).
- [ ] **`make backtest COMPETITION=<id>`** runs predictor swarm against the historical corpus, writes a `data/backtest/competition/<id>/<asof>.json` report (logloss + Brier + reliability bins).
- [ ] **Per-format calibration tolerance.** Tolerances live in `cfg.competition_calibration_tolerance_<format>` (defaults: `round_robin=1.10×`, `single_knockout=1.20×`, `two_leg_knockout=1.20×`, `group_round_robin=1.15×`, `final_only=1.30×`, `multi_stage_qualifier=1.25×`). The tolerances are documented; tightening one bumps `ai` minor.
- [ ] **Knockout-prior calibration.** Upset-prior in `knockout_continental_club` profile is fitted on real UCL knockout data (≥ 5 seasons), not picked by hand; the fit script `xops/leagues/fit_calibration.py` is part of the harness and is reproducible (deterministic seed).
- [ ] **Era-aware aggregation.** Two-leg backtests honour `away_goals_rule_active_until: 2021-05-31` for UEFA per `COMPETITIONS.md` §4 — proof test `test_away_goals_era_aware.py` runs a 2019-20 tie and a 2022-23 tie and asserts the aggregation differs.
- [ ] **Cross-tier mismatch tolerance.** Domestic-cup early rounds (Süper Lig vs Lig 1 club) widen CI per the `domestic_cup_early_round` profile; backtest must show calibration plot within `cfg.cup_early_round_calibration_max_deviation` (default 0.12 absolute deviation).
- [ ] **Power analysis at sample-size boundary.** `xops/leagues/power_analysis.py` computes the minimum N matches needed to detect a `cfg.league_calibration_max_deviation`-sized effect with power 0.8 α 0.05; if a candidate league's corpus is below the threshold, `make leagues.readiness` reports `insufficient_power` (not `pass`) for the calibration gate.
- [ ] **Reliability-diagram confidence intervals.** Each backtest report ships per-bin CIs (Wilson score for Bernoulli outcomes); promotion gate evaluates against the upper CI, not the point estimate — prevents flattering small-sample bins.
- [ ] **Time-series cross-validation.** Backtests use forward-chaining (train on weeks 1–N, test on N+1) per Phase 5 doctrine; `test_no_lookahead_in_backtest.py` asserts no test sample's `kickoff_utc` precedes its training cutoff.
- [ ] **Backtest determinism.** Re-running `make backtest COMPETITION=<id>` with the same `--seed` produces byte-identical reports (proof test `test_backtest_deterministic.py`); non-determinism is a CI fail.
- [ ] **Era-boundary backtest sweep.** For every era cutover declared in any `Competition.stages[*]` (away-goals, sub limit, ABBA penalties, VAR introduction), `xops/leagues/era_sweep.py` runs the backtest on ± N matches around the cutover and asserts the calibration plot drift is within `cfg.era_drift_tolerance`.
- [ ] **Cup-final empty-stadium guard.** Backtests for finals played behind closed doors (COVID era, sanctioned matches) carry the `crowd=absent` flag; if the predictor's home-advantage feature isn't zeroed, `test_neutral_crowd_zeros_home_adv.py` fails.
- [ ] **Multi-worker determinism.** `make backtest COMPETITION=<id> --workers=N` produces byte-identical reports for any `N ∈ [1, 16]` with the same `--seed` (proof test `test_backtest_parallel_determinism.py`); guards against numpy / torch worker-state leakage.
- [ ] **Backtest-cache key includes catalog hash.** Cached backtest report is keyed on `(competition_id, asof, catalog_sha256, calibration_profile_sha256, seed)`; a catalog edit invalidates stale reports automatically (proof test `test_backtest_cache_key_invalidates_on_catalog_change.py`).
- [ ] **Per-format backtest concurrency budget.** `make backtest --all` runs at most `cfg.backtest_concurrency_max` (default = vCPU count) competitions in parallel; CPU governor (Phase 11 §11.40) enforces; never starves predictor-serving threads.
