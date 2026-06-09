# Phase 13.26 — Catalog concurrency & atomic two-phase reload

> Extracted from `docs/planning/ROADMAP.md` §13.26
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.26 Catalog concurrency & atomic two-phase reload

> Retires assumption §13.0 #27.

- [x] **Two-phase reload.** `make leagues.reload` is `propose → validate → commit | abort`. Propose computes the new immutable view; validate checks against inflight predictor / proofreader requests (no inflight references a row whose tier-bearing field is mutating); commit atomically swaps the module-level `CATALOG` reference. Abort leaves the prior view fully active.
- [x] **Reader-no-tear guarantee.** Concurrent readers either see fully-prior or fully-new view, never a hybrid (proof test `test_catalog_reload_no_torn_read.py` runs 10 000 concurrent reads during a reload and asserts every read maps to one of the two snapshots).
- [x] **Inflight protection.** A reload that would change a tier-bearing field on a row with > 0 inflight predictions blocks for up to `cfg.catalog_reload_drain_max_s` (default 30) before aborting; abort writes a tracker row.
- [x] **Cluster-wide reload.** Multi-replica fleets coordinate the reload via Redis lock keyed on `catalog_sha256`; any replica still serving the old hash after `cfg.catalog_reload_propagation_max_s` (default 60) is paged via Phase 8.
- [x] **Hot-path reload safety.** Predictor / proofreader hot-paths read the catalog reference once per request (no per-row lookup chained inside a loop); proof test `test_catalog_ref_pinned_per_request.py`.
