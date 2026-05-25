# Phase 11.34 — Capacity admission for new agents & workloads

> Extracted from `docs/planning/ROADMAP.md` §11.34
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.34 Capacity admission for new agents & workloads

> **Why this exists.** "Schedule a fourth predictor replica on this
> host" is implicitly safe today only because the operator manually
> checked. Phase 8 scaler will not have that luxury.

- [ ] **Pre-flight check.** Adding a replica or a new workload class on a host requires `compute_router.preflight(workload_class, host)` to return `ok` against the live §11.1 inventory: `vram_required + ctx_overhead_mb`, `cpu_threads_required`, `nvram_required` (NPU memory), and `power_limit_required` all fit *concurrently* with the current resident set.
- [ ] **Atomic claim.** Successful preflight returns a short-lived reservation (`cfg.compute_preflight_reservation_ttl_s`, default 60 s) that the supervisor must redeem by actually starting the agent; expiring an unredeemed reservation frees the slot.
- [ ] **Refusal is structured.** Failure returns `{reason ∈ vram|ctx|cpu|npu|power|psu|fragmentation, available, required, alternates: [host…]}` so Phase 8 scaler can pick another host instead of blind-retrying.
- [ ] **Audit.** Every preflight (granted or refused) appends to the §11.2 arbiter audit stream; refusals are counted in `negelir_capacity_admission_refused_total{reason}`.
