# Phase 13.9 — Performance, efficiency, & footprint

> Extracted from `docs/planning/ROADMAP.md` §13.9
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.9 Performance, efficiency, & footprint

- [ ] **Catalog footprint cap.** Loaded catalog (50 rows + 200 competitions) ≤ `cfg.league_catalog_max_rss_mb` (default 8 MB resident); soak test `test_catalog_rss_under_cap.py`.
- [ ] **Lazy preset import.** `LEAGUE_CONFIGS` is a `LazyDict` — a preset module is imported only when its `league_id` is first accessed. Predictor cold-start with 30 leagues stays within Phase 11 §11.0 cold-start budget; benchmarked nightly (`make bench.leagues_coldstart`).
- [ ] **Gazetteer compile cache.** TR gazetteer compiled per league set + cache key `sha256(league_ids_sorted, gazetteer_version)`; recompile cost bounded; cache eviction LRU by Phase 11 §11.15 artifact-cache discipline.
- [ ] **Predictor replica admission.** Adding a league does **not** auto-spawn replicas; the Phase 8 scaler reads per-league traffic and requests new replicas through Phase 11 §11.34 preflight. Capacity refusal returns a structured reason; ops sees it on the console.
- [ ] **Tenant quota hooks** (Phase 20 dormant) — every league row carries a `default_tenant_class` so quota counters in §11.17 partition correctly when monetization flips on.
- [ ] **Catalog hot-reload (advisory).** Operator calls `make leagues.reload`; predictors that have already pinned a row continue with the prior view until next request — no in-flight prediction is interrupted (proof test `test_hot_reload_no_inflight_break.py`).
- [ ] **Per-league embedding budget.** Cross-competition identity (§13.4) reuses one shared embedding model across all leagues; per-league dedicated models are **forbidden** by lint (doctrine #4 — smallest model that works).
- [ ] **Catalog memory growth bound.** `bench/leagues_memory.py` asserts adding a league row grows resident memory by ≤ `cfg.league_per_row_max_kb` (default 64 KB) under realistic competition counts; regressions block CI.
- [ ] **Predictor inflight cap per league.** `cfg.predictor_inflight_max_per_league` (default 64) prevents one league from saturating the predictor swarm; overflow returns `503 Service Unavailable + X-Reason: per_league_inflight_full` (Phase 11 §11.30 backpressure).
