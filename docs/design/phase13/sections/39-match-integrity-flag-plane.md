# Phase 13.39 — Match-integrity flag plane

> Extracted from `docs/planning/ROADMAP.md` §13.39
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.39 Match-integrity flag plane

> Retires assumption §13.0 #46. Defensive: never publish a prediction
> for a fixture whose integrity is publicly questioned.

- [ ] **`IntegrityFlag` Reference-plane entity.** `(flag_id, fixture_id?, competition_id?, source_authority, severity ∈ {info, warn, suspended_competitively}, body_md, raised_at, resolved_at?)`.
- [ ] **Predictor refusal.** A fixture with an unresolved `severity=suspended_competitively` flag refuses prediction publish (`X-Reason: integrity_flag_active`); proof test `test_integrity_flag_blocks_publish.py`.
- [ ] **Tie propagation.** If one leg of a §13.12 two-leg tie is flagged, the entire tie is flagged (per `tie_id`); proof test `test_integrity_flag_propagates_across_legs.py`.
- [ ] **Source authorities.** Configurable per `xops/leagues/integrity_authorities.yaml` (UEFA Integrity, FIFA Integrity, national-FA bulletin URLs); flags from non-listed sources surface as `info` only.
- [ ] **Audit ledger.** Every flag mutation writes an audit-log entry per §13.21; resolution requires signed acknowledgement.
- [ ] **Frontend banner.** Phase 15 surfaces a Turkish banner "müsabaka soruşturma altında" for affected fixtures.
