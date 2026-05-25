# Phase 13.33 — Crowd-state plane

> Extracted from `docs/planning/ROADMAP.md` §13.33
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.33 Crowd-state plane

> Retires assumption §13.0 #40.

- [ ] **`Fixture.crowd_state` enum.** `{full, partial, behind_closed_doors, neutral, away_fans_banned, sanctioned_capacity_cap}`; never inferred from venue.
- [ ] **`Fixture.attendance_actual` Live-plane field.** Authoritative source per league; missing field allowed for T2 but required for T1 (`cfg.attendance_coverage_t1_min`, default 0.95).
- [ ] **Predictor home-advantage feature.** Reads the explicit `crowd_state` enum; `behind_closed_doors` and `neutral` zero the home-advantage component; `away_fans_banned` adds a small home-side bias (proof test `test_crowd_state_home_advantage.py`).
- [ ] **Sanction propagation.** A federation-published stadium-closure sanction (UEFA disciplinary) for the next N home fixtures auto-flips those fixtures to `behind_closed_doors`; reactor refuses silent sanction propagation (must be sourced).
- [ ] **Capacity-cap inference forbidden.** Lint (`xops/lint/no_capacity_cap_inference.py`) refuses any code that derives `crowd_state` from the ratio `attendance_actual / capacity`; the inference is always a federation-published fact.
