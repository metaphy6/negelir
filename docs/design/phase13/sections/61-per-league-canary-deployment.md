# Phase 13.61 — Per-league canary deployment

> Extracted from `docs/planning/ROADMAP.md` §13.61
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.61 Per-league canary deployment

> Retires assumption §13.0 #73.

- [ ] **`LeagueRow.deployment_phase ∈ {canary, full, withdrawn}`.** New T2 row defaults to `canary`; only `cfg.league_canary_pct` (default 5 %) of replicas serve it.
- [ ] **Canary metrics gate.** Promotion `canary → full` requires `cfg.league_canary_min_h` (default 24 h) of:
  - p99 prediction latency for the league within tier SLO
  - DLQ depth ≤ `cfg.league_canary_dlq_max`
  - Zero `proof.flag.v1` of severity `error`
  - Calibration deviation ≤ `cfg.league_canary_calibration_max`
- [ ] **Auto-withdraw on regression.** Canary failure auto-flips to `withdrawn` + tracker row + ops alert; withdrawn league refuses prediction publish until re-deployed.
- [ ] **Per-replica routing.** Phase 14 service mesh consumes `deployment_phase`; routing rule: canary leagues only reach replicas in the canary pool (declared via Phase 11 routing matrix §11.29).
- [ ] **Cross-region canary.** Canary first in one region, then expanded; full rollout requires green canary in every region.
