# Phase 11.40 — Phase 16 / 17 CPU governor binding (closing the cross-phase gap)

> Extracted from `docs/planning/ROADMAP.md` §11.40
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.40 Phase 16 / 17 CPU governor binding (closing the cross-phase gap)

- [ ] **Emitter under §11.3 governor.** The Phase 16 emitter is CPU-only by contract but still claims a thread budget via the §11.3 governor (default `cfg.emitter_thread_budget=2`). Without this, a busy emitter starves the predictor swarm sharing the host.
- [ ] **Patcher under §11.3 governor.** Same for the Phase 17 patcher harness (default `cfg.patcher_thread_budget=4`); plus the patcher container is built with the §11.11 `cpu_only` build tag and cannot import GPU SDKs even by accident.
- [ ] **Tested.** `test_emitter_thread_budget_respected`, `test_patcher_thread_budget_respected`.
