# Phase 16.20 — Performance budgets & load testing

> Extracted from `docs/planning/ROADMAP.md` §16.20
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.20 Performance budgets & load testing

- [ ] **Load test corpus** in `xops/feeds/loadgen.py`: synthetic 24 h burst at 10× the Phase 13a peak (estimated 3 000 records/s across all planes/sources combined), randomized payload sizes within the 64 KiB cap.
- [ ] **Budgets (binding):** sustained write throughput ≥ 5 000 records/s on a 4-core dev box with local disk; snapshot build ≤ 30 s for one hour of `score` plane at peak; reader `stream()` sustained ≥ 50 000 records/s on the same box; CPU ≤ 1.5 cores at the binding throughput; RSS ≤ 512 MiB per writer process.
- [ ] CI regression: `test_loadgen_meets_budget.py` runs a 30 s burst and fails if any budget regresses by > 20 % vs the recorded baseline (`xops/feeds/baseline.json`).
