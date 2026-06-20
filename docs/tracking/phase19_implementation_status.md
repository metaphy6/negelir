# Phase 19 Implementation Status

**Status:** In-Progress  
**Date Started:** 2026-06-20  
**Configuration Version:** ai-1.151.0

## Summary

Phase 19 (Global Catalog — deferred long-tail) implementation tracking across 14 sections (§19.6–§19.19) and 144+ bullets.

This document tracks:
- ✅ Complete bullets (code + tests shipped)
- 🟨 In-progress bullets (scaffolded, foundation laid)
- ⏳ Pending bullets (not yet started)

---

## Section Summary

| §    | Title | Bullets | Status | Notes |
|------|-------|---------|--------|-------|
| §19.6 | T3 resource governance & scrape-lane isolation | 11 | 🟨 | Config keys added; infrastructure pending |
| §19.7 | Catalog integrity & consistency at scale | 12 | 🟨 | Config keys added; validation pending |
| §19.8 | Per-league observability & SLOs | 11 | ⏳ | Test scaffolding started |
| §19.9 | Security, supply-chain & adversarial corpus | 13 | ⏳ | Not started |
| §19.10 | Catalog decommissioning & disaster recovery | 9 | ⏳ | Not started |
| §19.11 | Initial long-tail T3 roster (sample batch) | 7 | ⏳ | Sample data pending |
| §19.12 | Downstream coordination & Phase 22 pre-positioning | 7 | ⏳ | Not started |
| §19.13 | Data-sparse league calibration bootstrap | 5 | ⏳ | Config keys added |
| §19.14 | Season calendar & fixture calendar ingestion | 11 | 🟨 | Config keys added; calendar model pending |
| §19.15 | T3→T2 promotion ceremony & T2→T3 demotion | 12 | 🟨 | Config keys added; ceremony logic pending |
| §19.16 | Catalog schema versioning & migration | 9 | ⏳ | Schema v1→v2 pending |
| §19.17 | API catalog surface — pagination & filtering | 17 | 🟨 | Config keys added; endpoint pending |
| §19.18 | Definition of Done | 23 | ⏳ | Checklist pending verification |
| §19.19 | Fixture lifecycle — timezone & deduplication | 17 | 🟨 | Config keys added; resolver pending |
| **TOTAL** | | **144** | **🟨** | **Infrastructure foundation: config keys ✅** |

---

## Infrastructure Completed

### Phase 19 Config Keys (added to `ai/common/config.py`)

✅ T3 resource governance:
- `t3_scrape_concurrency` (default: 2)
- `t3_scrape_rate_limit_rps` (default: 0.05)
- `t3_scrape_budget_per_league_s` (default: 10)
- `t3_predictor_max_cpu_cores` (default: 0.25)
- `t3_source_grace_period_hours` (default: 48)
- `t3_prediction_retention_days` (default: 365)
- `t3_prediction_reaper_utc_hour` (default: 3)

✅ Catalog & API surface:
- `catalog_reload_slo_ms` (default: 500)
- `catalog_max_leagues` (default: 500)
- `api_catalog_page_limit_max` (default: 50)
- `api_league_listing_latency_p99_ms` (default: 80)
- `api_max_response_body_kb` (default: 128)

✅ Timezone & fixture handling:
- `fixture_timezone_resolver_path`
- `fixture_dedup_window_minutes` (default: 120)
- `fixture_dedup_quarantine_hours` (default: 6)

✅ Calibration bootstrap & promotion:
- `bootstrap_peer_max` (default: 5)
- `bootstrap_ci_widen_factor` (default: 1.5)
- `promotion_preflight_max_age_hours` (default: 24)

---

## Implementation Roadmap

The remaining 144 bullets require:

1. **T3 Scraper Infrastructure** (§19.6)
   - Separate scrape lane with Redis queue namespacing
   - Per-league budget tracking and enforcement
   - Automatic shelving on source unavailability

2. **Catalog Scale Operations** (§19.7)
   - Msgpack binary cache for hot path
   - Catalog migration utilities (v1→v2 schema)
   - Incremental validation pipeline

3. **Observability & Metrics** (§19.8)
   - T3-prefixed metric emission
   - Staleness detection & alerts
   - Per-league readiness reports

4. **API Pagination** (§19.17)
   - GET /v1/leagues endpoint with cursor
   - ETag & conditional request support
   - Response size SLO enforcement

5. **Fixture Lifecycle** (§19.19)
   - Timezone resolver & UTC normalization
   - Cross-source deduplication
   - Prediction record reaping

---

## Test Scaffolding

File: `ai/tests/test_phase19_long_tail_catalog.py`

Tests defined for:
- Config key presence verification
- T3 resource governance constraints
- Catalog integrity SLOs
- API surface contracts
- Timezone resolution

**Status:** Tests failing on Config() instantiation (import path issue); requires env var fix.

---

## Blocking Items

1. **Config import path** — `ai/common/config.py` uses `from common.season import current_season` which fails without proper PYTHONPATH. Workaround: set `NEGELIR_COMMON_DEFAULT_SEASON` env var.

2. **Full implementation requires:**
   - Scraper refactoring for lane isolation
   - Redis key namespace validation
   - API handler implementation
   - Fixture processor modifications
   - ~4–6 weeks of development for all 144 bullets

---

## Next Steps

1. Fix Config import path or document PYTHONPATH requirement
2. Implement §19.6 infrastructure (T3 scrape lane)
3. Implement §19.7 infrastructure (catalog validation)
4. Continue systematically through §19.8–§19.19
5. Update tracker rows for each completed section

---

*Last updated: 2026-06-20*
*Tracker rows: 1 (foundation); version bump: ai-1.151.0*
