# Phase 13.28 — Per-league red-team & adversarial corpus

> Extracted from `docs/planning/ROADMAP.md` §13.28
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.28 Per-league red-team & adversarial corpus

> Retires assumption §13.0 #29. Complements Phase 12 with
> league-specific attacks.

- [x] **Per-league corpus directory.** `ai/tests/fixtures/adversarial/leagues/<league_id>/` with at least the following families:
  - **Alias collision** — near-duplicate club names within and across confederations (covered structurally by §13.4 but evaluated per league).
  - **Calibration poisoning** — synthetic-but-plausible historical results crafted to shift a league's prior; predictor must reject (Phase 7 sec.input).
  - **Fixture lifecycle abuse** — a postpone/reschedule loop (oscillating state) that would amplify `predict.invalidated` events; reactor must rate-limit (`cfg.fixture_invalidation_rate_max_per_h`).
  - **Time-zone spoofing** — a source returning kickoff in `UTC+14:00` for a Süper Lig fixture; tz validation must refuse.
  - **Identity-merge attacks** — crafted alias chains that would walk the resolver across two distinct clubs; resolver must hold the merge boundary.
  - **Two-leg tie replay attacks** — duplicate leg events with mutated scores; reactor idempotency must hold.
- [x] **Per-league suite must be green before T1 promotion.** §13.7 readiness gate consults the suite's pass-rate; any `xfail` in the suite blocks promotion.
- [x] **Corpus growth on regression.** Every demotion / quarantine / Phase 17 patcher artifact whose root cause maps to one of the above families auto-appends a regression case to the corpus (with a tracker row). Suite is monotonically growing.
