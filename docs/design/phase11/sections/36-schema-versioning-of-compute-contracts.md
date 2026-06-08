# Phase 11.36 — Schema versioning of compute contracts

> Extracted from `docs/planning/ROADMAP.md` §11.36
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.36 Schema versioning of compute contracts

> **Why this exists.** Every JSON contract in §11.* is on a path to
> drift silently when a future agent edits it without thinking about
> backward-compat. The repo has versioning discipline (`xops/versioning/`)
> for code; compute contracts get the same treatment here.

- [x] **`schema_version` on every JSON.** `device.json`, `workload_matrix.json`, `engines.json`, `quirks.json`, `runtime_matrix.json`, `shadow_promotion.json`, `cost_table_*.json`, and the `compute_provenance` block all carry `schema_version: "<major>.<minor>"`. Loaders refuse unknown major; warn on unknown minor.
- [x] **Migration ledger.** `xops/compute/schema_migrations/<contract>/<from>__to__<to>.py` is a pure-function migration; the loader applies the chain on read for `<minor>` bumps. `<major>` bumps require a tracker row + `make version.bump COMPONENT=ai LEVEL=minor`.
- [x] **Provenance-replay compat matrix.** Replay (§11.15) declares the oldest `compute_provenance.schema_version` it can replay; older provenance returns `replay_unsupported` with the bridge tool name. Documented in `COMPUTE_DEVICES.md`.
- [x] **Lint.** `xops/lint/compute_schema_versions.py` refuses a commit that mutates one of the contracts without bumping its `schema_version` or adding a no-op migration entry.
