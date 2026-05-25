# Phase 13.31 — Weather plane

> Extracted from `docs/planning/ROADMAP.md` §13.31
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.31 Weather plane

> Retires assumption §13.0 #38. Lightweight first; full enrichment in
> Phase 21.

- [ ] **`Weather` Live-plane entity.** `(fixture_id, observed_at, temp_c, wind_kmh, precip_mm_h, humidity_pct, pitch_condition_enum, source_id)`; `pitch_condition_enum ∈ {dry, damp, wet, frozen, snow, sand}`.
- [ ] **Optional, non-blocking.** Missing weather logs `negelir_fixture_weather_missing_total{league_id}` but never blocks publish; T1 promotion requires `coverage ≥ cfg.league_weather_coverage_min` (default 0.80) over the last 60 days.
- [ ] **Weather-source registry.** `xops/leagues/weather_sources.yaml` per region; sources rate-limited per Phase 4 budget; offline-mock pinning via §13.6 mock-stack.
- [ ] **Predictor feature gating.** Weather features attach only when observation timestamp is within `cfg.weather_freshness_max_h` (default 6 h) of kickoff; stale weather is dropped, not back-filled (no fabrication).
- [ ] **Per-competition opt-in.** `Competition.uses_weather_features: bool` — turfed indoor competitions (futsal-style or roofed venues) opt out; proof test `test_indoor_competition_no_weather.py`.
- [ ] **Catastrophic-weather fixture interaction.** Per §13.17, a weather-driven postponement (snow-out) is emitted as a `postponed` lifecycle event with `reason=weather`; predictor invalidates and waits for reschedule.
- [ ] **Weather-source rate-limit budget.** Weather scrapers participate in §13.55 per-league × per-source token budget; weather feed never starves a sport-data feed of the same provider (proof test `test_weather_does_not_starve_sport_feed.py`).
- [ ] **Per-region weather-source failover.** Each region carries a primary + secondary weather provider; failover within `cfg.weather_failover_max_s` (default 30 s) on primary 5xx; both providers' observations stored with `field_provenance` per §13.36.
