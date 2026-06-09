# Phase 13.23 — Fairness & bias detection

> Extracted from `docs/planning/ROADMAP.md` §13.23
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.23 Fairness & bias detection

> Retires assumption §13.0 #24. Ensures the predictor's errors are
> not systematically concentrated on certain teams, referees, or
> kickoff slots.

- [x] **Per-segment residual audit.** Nightly `xops/leagues/bias_audit.py` computes residuals by segment; emits flags when |residual| > threshold over 90-day window. Landed: audit module + flag emission implemented.
- [x] **Proofreader veto on systemic bias.** Phase 6 proofreader vetoes T2→T1 promotion on sustained bias. Landed: veto logic implemented.
- [x] **Referee-aware feature isolation.** Referee dominance shrinkage per config; proof test confirms feature shrinking. Landed: shrinkage logic implemented.
- [x] **Per-tier-mismatch fairness.** Upset calibration audit & separate metric per league. Landed: metric exported.
