# Phase 11.30 — Backpressure HTTP semantics (binding for Phase 9 API)

> Extracted from `docs/planning/ROADMAP.md` §11.30
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.30 Backpressure HTTP semantics (binding for Phase 9 API)

> **Why this is binding.** "Service busy" with no headers is a debugging
> nightmare; "Service busy" with predictable, bounded `Retry-After` is
> a contract upstream consumers can build on.

- [ ] **Status-code matrix.**
  - Saturated routing (§11.13 admission) → **HTTP 503** + `Retry-After: <seconds, integer>` + `X-Compute-Reason: router_admission_full`.
  - Per-tenant quota exceeded (§11.17) → **HTTP 429** + `Retry-After` + `X-Compute-Reason: tenant_quota_exceeded`.
  - VRAM budget refused at scale-up (Phase 8 / §11.10 row 13) → **HTTP 503** + `Retry-After` + `X-Compute-Reason: vram_budget_exceeded`.
  - Spot-eviction in progress (§11.23) → **HTTP 503** + `Retry-After` + `X-Compute-Reason: spot_draining`.
  - All devices `degraded` for the workload class → **HTTP 503** + `Retry-After: <unbounded ⇒ value bounded by cfg.api_retry_after_max_s>` + `X-Compute-Reason: no_eligible_device`.
- [ ] **`Retry-After` bounds.** Computed from the arbiter's queue model (`expected_wait = qd × p95_recent`) clamped to `[cfg.api_retry_after_min_s, cfg.api_retry_after_max_s]`. Never `0`, never unbounded.
- [ ] **`X-Compute-Reason` enum.** Closed enum, documented in `docs/design/COMPUTE_DEVICES.md`; lint refuses ad-hoc strings.
- [ ] **Tested end-to-end.** A Phase 12 chaos scenario forces each row above and asserts the exact triple `(status, Retry-After, X-Compute-Reason)`.
