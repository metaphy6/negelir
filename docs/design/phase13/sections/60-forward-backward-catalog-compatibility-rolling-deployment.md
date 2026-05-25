# Phase 13.60 — Forward + backward catalog compatibility & rolling deployment

> Extracted from `docs/planning/ROADMAP.md` §13.60
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.60 Forward + backward catalog compatibility & rolling deployment

> Retires assumption §13.0 #72. Old replicas mid-rolling-deploy must
> not crash on a v_N catalog they don't fully understand.

- [ ] **Catalog reads `schema_version ∈ [N-1, N]`.** Loader downshifts by replaying §13.27 down-migrations for unknown N+ fields; lint refuses removing the down-migration before `removed_in`.
- [ ] **Rolling-deployment soak.** `make chaos.rolling.catalog` rolls `schema_version: N` across half the replicas while the other half still run binary v_{N-1}; no replica crashes; both halves serve traffic for the full soak (proof test `test_rolling_deployment_catalog_compat.py`).
- [ ] **Cross-version response equivalence.** For every endpoint, v_{N-1} and v_N replicas return semantically equivalent responses for the same request during the rolling window (Phase 9 contract-test gate).
- [ ] **Forward-only mutation refusal.** A v_{N-1} binary asked to *write* a v_N-only field refuses with structured error; never silently drops (proof test `test_old_binary_refuses_new_field_write.py`).
- [ ] **Schema-version probe.** `/healthz` exposes `catalog_schema_version`; Phase 14 deployer uses it to drive the rolling order (oldest first).
