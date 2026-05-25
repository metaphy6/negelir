# Phase 11.29 — Hot-reload of routing & workload matrices

> Extracted from `docs/planning/ROADMAP.md` §11.29
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.29 Hot-reload of routing & workload matrices

- [ ] **`workload_matrix.json` hot-reload.** mtime poll every `cfg.compute_router_reload_s` (default 30 s); atomic swap (parse → validate → swap pointer); failed parse keeps prior matrix and emits `route.alert.v1{kind=matrix_reload_failed, severity=error}`.
- [ ] **Sticky in-flight respect.** A reload never breaks an in-flight session's stickiness mid-decode; new sessions and post-eviction re-routes pick up the new matrix.
- [ ] **K8s parity.** Same K8s mtime gotcha as the §7 `sec.input` pattern hot-reload — `kubectl rollout restart` is the prod path; the in-pod mtime poll is the dev path. Documented.
- [ ] **Audit.** Each reload emits `route.matrix.v1{sha256, by, source}`; tested.
