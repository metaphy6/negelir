# Phase 18.3 §18.3 — Shim Deletion Pre-Conditions & CODEOWNERS Acks

**Status:** Binding pre-conditions for Phase 22 §22.4 shim deletion.

**Ledger #5:** Three signals must all be green for 14 days before `ai/` is deleted in Phase 22:
1. Zero `ai.*-shim` `DeprecationWarning`s in CI (≥ 50 pipelines)
2. Zero hits in production runtime logs (`make shim.runtime.report`)
3. **CODEOWNERS ACK from each component** (checked into this file)

This file is CODEOWNERS-protected. Each component owner MUST explicitly ACK
the removal of the shim before Phase 22 §22.4 deletion can proceed.

---

## Component Owner ACKs

| Component | Owner(s) | Status | Date | Notes |
|-----------|----------|--------|------|-------|
| datasource | *TBD* | ⏳ pending | — | Awaiting explicit ACK via PR |
| swarm | *TBD* | ⏳ pending | — | Awaiting explicit ACK via PR |
| server | *TBD* | ⏳ pending | — | Awaiting explicit ACK via PR |
| common | *TBD* | ⏳ pending | — | Awaiting explicit ACK via PR |

---

## Pre-Condition Status

### Signal 1: CI DeprecationWarning Count
- **Requirement:** Zero `ai.*-shim` `DeprecationWarning`s over rolling 14-day window (≥ 50 CI pipelines)
- **Status:** ⏳ Pending Phase 22 execution
- **Command:** `make shim.ci_warnings.report`

### Signal 2: Production Runtime Logs
- **Requirement:** Zero `ai/` references in production runtime logs over rolling 14-day window
- **Status:** ⏳ Pending Phase 22 execution
- **Command:** `make shim.runtime.report`

### Signal 3: CODEOWNERS Acks
- **Requirement:** All four component owners explicitly ACK the shim deletion
- **Status:** ⏳ Pending owner PRs
- **Tracking:** This file (CODEOWNERS-protected)

---

## When Phase 22 §22.4 Executes

Phase 22 §22.4 deletion is **blocked** until ALL three signals are green.

The deletion must be proceeded by:
1. ✅ `make isolation.shims-only` is green in CI (proof that `ai/` contains only re-exports)
2. ✅ All three pre-condition signals have been green continuously for 14 days
3. ✅ This file shows all four CODEOWNERS acked

At that point, Phase 22 §22.4 runs the two-PR sequence to delete `ai/`.

---

## Reference

- **ROADMAP:** `docs/planning/ROADMAP.md` §18.3
- **Design:** `docs/design/COMPONENT_LAYOUT.md` §6 (component ownership)
- **Ledger #5:** Proof ledger in ROADMAP.md §18.0 ("Shim deletion is signalled by...")
