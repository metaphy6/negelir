# Phase 13.49 — Storage-independent cold-start

> Extracted from `docs/planning/ROADMAP.md` §13.49
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.49 Storage-independent cold-start

> Retires assumption §13.0 #61. A predictor / proofreader replica
> must boot deterministically even when Postgres / Redis are
> unavailable — the catalog (high-trust YAML + signed audit ledger)
> is the only file the cold-start path requires.

- [x] **Boot-order contract.** Replica startup: (1) load YAML + verify §13.21 signature chain; (2) pin module-level `CATALOG`; (3) open `/livez` (returns OK as soon as 1+2 complete); (4) attempt storage joins with bounded back-off; (5) only after storage joins does `/readyz` flip to OK. Phase 11 §11.44 probes consume the contract.
- [x] **No storage call in catalog loader.** Lint (`xops/lint/no_storage_in_catalog_loader.py`) refuses any `psycopg`, `redis`, `aiohttp`, or `requests` import inside `ai/common/league_catalog_loader.py` and its transitive imports. Proof test `test_catalog_loader_no_storage_imports.py`.
- [x] **Cold-start under fault injection.** `make chaos.storage.deny` denies all DB / Redis traffic at the network layer; replica must reach `/livez=OK` within `cfg.compute_cold_start_max_ms` (Phase 11 §11.0) and serve a `503 + X-Reason: storage_unavailable` for any `/v1/predict` request. Proof test `test_cold_start_under_storage_outage.py`.
- [x] **Catalog-only sandbox replay.** `make leagues.sandbox.smoke OFFLINE=1` runs the §13.43 sandbox lane with **no** storage layer attached; predictor's catalog-derived branches (calibration profile resolution, tier surface, market roster) all execute correctly.
- [x] **Audit-ledger replay budget.** Boot-time signature-chain verification (audit ledger up to `cfg.league_audit_compaction_days` worth of entries) completes in ≤ `cfg.league_audit_boot_verify_max_ms` (default 250 ms) on the smallest CI lane; soak `bench/audit_replay_boot.py`.
