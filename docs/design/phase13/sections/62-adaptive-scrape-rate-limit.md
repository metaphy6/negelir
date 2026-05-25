# Phase 13.62 — Adaptive scrape rate-limit

> Extracted from `docs/planning/ROADMAP.md` §13.62
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.62 Adaptive scrape rate-limit

> Retires assumption §13.0 #74.

- [ ] **Adaptive controller.** Token-bucket refill rate adjusts based on observed upstream `429 Too Many Requests` / `503 Service Unavailable` / `Retry-After` headers; AIMD (additive-increase, multiplicative-decrease) per `cfg.scrape_aimd_alpha` (default +5 %/min on success) and `cfg.scrape_aimd_beta` (default ×0.5 on 429).
- [ ] **Hard cap.** Refill rate bounded by `[cfg.scrape_min_rps, cfg.scrape_max_rps]` per source; runaway prevented (proof test `test_adaptive_rate_bounded.py`).
- [ ] **Audit topic.** `scrape.adaptive.v1{source_id, prior_rps, new_rps, reason ∈ {429, 503, retry_after, success_ramp}, observed_at}`; surfaces in Phase 8 console.
- [ ] **Robots.txt + ToS interaction.** Adaptive controller never exceeds `robots.txt`-declared crawl-delay regardless of upstream success signal (proof test `test_adaptive_respects_robots_crawl_delay.py`).
- [ ] **Per-league propagation.** Per §13.55, source-aggregate rate change propagates to per-league sub-buckets proportionally.
- [ ] **Cool-down on drift.** Sustained 429 (> `cfg.scrape_drift_cooldown_min` minutes, default 15) parks the source in a Phase 7 sec.input quarantine until ops acks (prevents accidental DoS).
