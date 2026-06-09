# Phase 13.63 — Per-league calibration mutation audit

> Extracted from `docs/planning/ROADMAP.md` §13.63
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.63 Per-league calibration mutation audit

> Retires assumption §13.0 #75.

- [x] **Calibration YAMLs follow §13.21 audit chain.** Every edit produces `data/leagues/audit/calibration/<utc_ts>.json` with actor, before/after sha256, signed; loader verifies on boot.
- [x] **Tracker row + chart bump per edit.** Lint refuses a calibration YAML diff in a commit without a matching `phases.csv` append + `xops/versioning/chart.json` bump for the affected league.
- [x] **Shadow-window reuse.** Per §11.26 / §13.2 profile drift guard, calibration edits go through a 14-day shadow window before going live.
- [x] **Readonly mode.** `cfg.league_calibration_readonly=true` per league freezes calibration mutations (mid-season per §13.18).
- [x] **Tamper-detection.** `make leagues.calibration.audit.verify` walks the chain; mismatch quarantines the calibration profile (predictor falls back to `default` until ops investigates).
