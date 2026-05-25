# Phase 13.54 — Prediction integrity & signed envelopes

> Extracted from `docs/planning/ROADMAP.md` §13.54
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.54 Prediction integrity & signed envelopes

> Retires assumption §13.0 #66. Predictions are first-class
> security artifacts; tampering must be detectable.

- [ ] **Signed envelope.** Every published prediction wraps in `{prediction_id, fixture_id, payload, catalog_sha256, calibration_profile_sha256, bundle_sha256, predictor_replica_id, signed_at, signature}`; signature uses the replica's per-bundle key (Phase 11 §11.45 KMS-wrapped).
- [ ] **`make predictions.audit.verify ASOF=<utc>`** walks all envelopes in a window; verifies every signature; computes a merkle root; outputs a one-line attestation.
- [ ] **Revision causality.** A revision (`revision++`) requires a published cause: `revision_cause ∈ {data_correction, fixture_lifecycle, retroactive_sanction, calibration_profile_update, demotion_revoke}`; lint refuses a publish without a documented cause for `revision > 0` (proof test `test_revision_requires_cause.py`).
- [ ] **Tamper-detection drill.** `make chaos.predictions.tamper FIXTURE_ID=<id>` mutates a stored envelope's payload; `make predictions.audit.verify` must detect and emit `predictions.tamper_detected.v1{prediction_id, observed_sha, expected_sha}` within `cfg.predictions_tamper_detection_max_s` (default 60 s). Proof test `test_predictions_tamper_detection.py`.
- [ ] **Revoke-on-demote propagation.** Per §13.66, demoting a league emits a `revision_cause=demotion_revoke` envelope with `payload.void=true`; downstream Phase 16 emitter shards re-emit; client-facing API returns the void payload + the original `predicted_at` for transparency.
- [ ] **Per-league signing key.** Bundle keys are partitioned per `league_id` so revoking one league's key (e.g. compromise) does not invalidate others (proof test `test_per_league_key_isolation.py`).
