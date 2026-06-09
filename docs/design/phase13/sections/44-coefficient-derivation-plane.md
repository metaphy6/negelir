# Phase 13.44 — Coefficient-derivation plane

> Extracted from `docs/planning/ROADMAP.md` §13.44
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.44 Coefficient-derivation plane

> Retires assumption §13.0 #51. Defensive — federation-published
> coefficients are sometimes wrong / late.

- [x] **`xops/leagues/coefficients.py`.** Computes UEFA / FIFA / continental coefficients from our own historical results; deterministic seed; reproducible.
- [x] **Lineage proof.** `make leagues.coefficients.derive --asof=<utc>` produces a JSON with every input fixture's `(stable_id, fixture_id, weight)` and a SHA-256 of the input set; proof test `test_coefficient_lineage_reproducible.py`.
- [x] **Drift alert vs federation number.** Computed coefficient is compared against the federation-published value; drift > `cfg.coefficient_drift_max` (default 0.05) raises `proof.flag.v1{kind=coefficient_drift}`.
- [x] **No fabrication.** Lint refuses a hand-typed coefficient table in `swarm/` or `ai/` (doctrine #3).
- [x] **Predictor consumption.** Coefficients feed the cross-competition strength prior (e.g. UCL group seeding); the prior is read at inference, not memoised.
