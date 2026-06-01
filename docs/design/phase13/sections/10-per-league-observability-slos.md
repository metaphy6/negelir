# Phase 13.10 — Per-league observability & SLOs

> Extracted from `docs/planning/ROADMAP.md` §13.10
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.10 Per-league observability & SLOs

- [ ] **Five canonical metrics** per league, exposed by Phase 11 telemetry:
  - `negelir_league_ingest_lag_seconds{league_id, plane}`
  - `negelir_league_prediction_emit_total{league_id, format, status}`
  - `negelir_league_calibration_deviation{league_id, window=7d|14d|30d}`
  - `negelir_league_dlq_depth{league_id, topic}`
  - `negelir_league_scraper_success_ratio{league_id, source}`
- [ ] **Per-league SLO contract** documented in `docs/design/LEAGUE_CATALOG.md` §11 (added in this phase): T1 = 99.5 % scraper success, ≤ 60 s ingest lag p95; T2 = 98 % / 180 s.
- [ ] **Burn-rate alerts** wired against the catalog row's tier — alerts route to the ops console (Phase 8) with `league_id` as a primary label.
- [ ] **Predictor vote dominance metric.** `negelir_league_vote_dominance{league_id}` ≤ 0.6 (no single predictor dominates) — verified at promotion (LEAGUE_CATALOG.md §2.1) and continuously.
- [ ] **Cardinality budget.** Total label cardinality across the five metrics ≤ `cfg.league_metrics_cardinality_budget` (default 50 leagues × 9 planes × 5 sources ≈ 2 250); exceeding the budget is a CI fail.
- [ ] **Per-league error budget + burn-rate policy.** Each tier carries a 30-day error budget (T1 = 0.5 % unavailability, T2 = 2 %); fast-burn (>2x in 1 h) pages immediately, slow-burn (>1x sustained 6 h) opens a tracker row. Documented in `LEAGUE_CATALOG.md` §11.
- [ ] **Vote-dominance with confidence interval.** The dominance metric reports its 95 % CI; promotion gates against the upper bound, not the point estimate.

#### 13.10.5 T2 dwell-time ceiling

- [ ] **Hard wall-clock ceiling.** A league sitting at T2 longer than `cfg.league_t2_max_dwell_days` (default 180) auto-demotes to T3 with a tracker row + ops alert (`league_t2_dwell_exceeded`); proof test `test_t2_dwell_ceiling.py`. Prevents permanent-beta drift. (Retires assumption §13.0 #35.)
- [ ] **Dwell-clock pause.** The dwell clock pauses while a league is `quarantined` (§13.15) or its source coverage drops below T2 minimums; resume timestamp is audited.
