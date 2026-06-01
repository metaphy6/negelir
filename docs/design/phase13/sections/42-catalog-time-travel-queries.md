# Phase 13.42 — Catalog time-travel queries

> Extracted from `docs/planning/ROADMAP.md` §13.42
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.42 Catalog time-travel queries

> Retires assumption §13.0 #49.

- [ ] **`/v1/catalog?asof=<utc>` endpoint.** Returns the catalog as it was at that UTC moment by replaying §13.21 audit-ledger entries onto a snapshot baseline.
- [ ] **Bounded asof range.** `asof` accepted within `cfg.catalog_asof_max_age_days` (default 730 = 2 years); requests outside range return `400 + X-Reason: asof_out_of_range`.
- [ ] **Replay determinism.** Two calls with the same `asof` return byte-identical bodies (proof test `test_catalog_asof_deterministic.py`).
- [ ] **Audit integration.** Time-travel reads do not write audit entries (read-only) but emit a `catalog.timetravel.v1{actor, asof, etag}` low-volume log line.
- [ ] **Patcher / ops-console consumption.** Phase 17 patcher and Phase 8 ops console can reproduce a historical decision by joining `prediction.created_at` with the catalog `asof`.
