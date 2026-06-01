# Phase 13.55 — Per-league × per-source scrape budget

> Extracted from `docs/planning/ROADMAP.md` §13.55
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.55 Per-league × per-source scrape budget

> Retires assumption §13.0 #67. A token-bucket per host (Phase 4) is
> not enough — a popular league must not starve a quieter league of
> the same source's rate limit.

- [ ] **Two-dimensional token bucket.** Keyed on `(source_id, league_id)`; per-source aggregate cap (Phase 4) divided across leagues by per-league `priority_weight` declared in the catalog row (default 1.0); proof test `test_scrape_bucket_partitions_correctly.py`.
- [ ] **Fairness floor.** Each league guaranteed ≥ `cfg.scrape_per_league_floor_pct` (default 5 %) of any source's bucket regardless of priority; prevents tier-T1-dominance drowning T2 (proof test `test_scrape_fairness_floor.py`).
- [ ] **Burst budget.** Per-league bucket allows a `cfg.scrape_burst_factor` (default 2×) burst over a `cfg.scrape_burst_window_s` (default 60 s); audited so a league cannot indefinitely burst.
- [ ] **Demotion / quarantine respects.** A quarantined league's bucket is set to 0 (refresh blocked); restored on un-quarantine.
- [ ] **Adaptive-rate-limit interaction.** §13.62 adaptive backoff applies at the source-aggregate level; per-league sub-buckets shrink proportionally; proof test `test_adaptive_backoff_propagates_to_per_league_buckets.py`.
