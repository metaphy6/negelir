# Phase 13.66 — Demotion-cascade safety + prediction revocation

> Extracted from `docs/planning/ROADMAP.md` §13.66
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.66 Demotion-cascade safety + prediction revocation

> Retires assumption §13.0 #78.

- [ ] **Atomic revoke.** Demoting a league transactionally:
  - flips `tier` per §13.8;
  - emits `revision_cause=demotion_revoke` envelopes (per §13.54) for every inflight T1-only prediction;
  - quarantines downstream cup competitions whose calibration depends on it (e.g. demoting La Liga quarantines Copa del Rey predictions until §13.7 re-passes).
- [ ] **Idempotency.** Re-running the demotion handler on the same input is a no-op (proof test `test_demotion_cascade_idempotent.py`).
- [ ] **Rollback within-window.** A demotion reversed within `cfg.demotion_revoke_grace_min` (default 30 min) un-revokes predictions transparently (revisions remain monotonic per §13.54).
- [ ] **Cascade audit.** `cascade.demotion.v1{trigger_league_id, affected_leagues[], affected_competitions[], revoked_prediction_count}` on Phase 8 console.
- [ ] **No silent fallback.** Per doctrine #3, the predictor must not silently substitute a "default" calibration to keep publishing during cascade quarantine; explicit refusal only.
