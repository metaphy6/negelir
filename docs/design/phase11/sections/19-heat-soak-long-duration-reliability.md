# Phase 11.19 — Heat-soak & long-duration reliability

> Extracted from `docs/planning/ROADMAP.md` §11.19
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.19 Heat-soak & long-duration reliability

- [ ] **Soak harness.** `make soak.compute DURATION=24h` runs every workload class in a closed-loop generator at production-shaped concurrency for the full duration; produces a report with throughput / latency / VRAM / temperature / power / ECC / xid / leak deltas in 1-minute buckets, plus a pass/fail per dimension.
- [ ] **Pass criteria.** Over 24 h: zero unrecoverable Xid; ECC retired-pages delta = 0; VRAM-PID growth ≤ `cfg.compute_leak_tolerance_mb`; temperature steady-state below thermal-throttle floor; throughput regression vs first-hour baseline within `cfg.soak_throughput_drift_pct` (default 5 %).
- [ ] **Thermal-cycle test.** A short variant (`make soak.compute.thermal DURATION=2h`) deliberately ramps load up/down to provoke thermal cycling; the GPU clock-state machine must converge (no oscillation > `cfg.soak_clock_oscillation_max_per_min`).
- [ ] **Reports.** `docs/reports/bench/soak-<date>.md`; archived under git LFS or a docs-site asset bucket. The ROADMAP DoD requires the most recent soak report be ≤ 30 days old.
