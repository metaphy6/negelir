# Phase 13.65 — Cross-competition prediction-consistency oracle

> Extracted from `docs/planning/ROADMAP.md` §13.65
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.65 Cross-competition prediction-consistency oracle

> Retires assumption §13.0 #77.

- [x] **Consistency oracle.** `swarm/proofreader/cross_competition_consistency.py` joins per-team strength priors across competitions; computes per-team delta over a rolling window.
- [x] **Threshold.** `cfg.cross_competition_consistency_max_delta` (default 0.08 in normalised strength units); breach raises `proof.flag.v1{kind=cross_competition_inconsistency, stable_id, competitions[]}`.
- [x] **Promotion gate.** Sustained consistency breach for a league blocks T2→T1 promotion (per §13.7 readiness).
- [x] **Permitted divergence.** A documented per-league `home_advantage_premium` may justify part of the delta; oracle subtracts the documented premium before evaluating the threshold.
- [x] **Backtest validation.** `test_cross_competition_consistency_threshold_well_chosen.py` confirms historical UCL participants from top-5 leagues fall within the threshold using realised priors.
