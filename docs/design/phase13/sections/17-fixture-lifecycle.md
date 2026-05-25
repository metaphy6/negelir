# Phase 13.17 — Fixture lifecycle (postpone / abandon / replay / awarded)

> Extracted from `docs/planning/ROADMAP.md` §13.17
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.17 Fixture lifecycle (postpone / abandon / replay / awarded)

> Fixtures are not immutable. A fixture may be postponed, rescheduled,
> abandoned mid-match, replayed entirely, awarded by federation
> committee (forfeit / 3-0 walkover), or annulled. Each transition
> invalidates downstream predictions and forces a revision bump.
> Retires assumption §13.0 #18.

- [ ] **`Fixture.status` FSM.** `scheduled → live → completed` is the happy path; off-path transitions: `scheduled → postponed → rescheduled (new fixture_id, original_fixture_id link) | cancelled`, `live → suspended → resumed | abandoned`, `completed → annulled | awarded(score, reason)`. FSM lives in `common/schemas/fixture_lifecycle.py`; transitions are deterministic and append-only-audited.
- [ ] **Prediction invalidation event.** Any non-terminal exit (`postponed`, `abandoned`, `annulled`, `awarded`) emits `predict.invalidated.v1{fixture_id, prior_revision, new_state, reason}`; Phase 16 emitter re-shards.
- [ ] **Per-state proof tests.** `test_fixture_lifecycle_<state>.py` for each transition: postpone-then-reschedule keeps `original_fixture_id` linkage; abandoned-with-resumption splits into `original_id (abandoned, score=at-suspension)` + `new_id (resumed, format=continuation)`; awarded-walkover overrides the on-pitch score with provenance `awarded_by=federation, reason=...`.
- [ ] **Revision monotonicity.** Each lifecycle transition bumps `Fixture.revision`; downstream consumers gate on `revision >= last_seen` (proof test `test_fixture_revision_monotonic.py`).
- [ ] **Two-leg tie cancellation.** §13.12 reactor must consume invalidation events and re-emit ties accordingly (covered by §13.12's leg-cancellation propagation test).
- [ ] **Walkover calibration.** Awarded walkovers (3-0 default by FIFA convention) feed neither the calibration corpus nor the betting-market predictor; sentiment + news consume them with a `synthetic=true` flag (proof test `test_walkover_excluded_from_calibration.py`).
- [ ] **Operator override CLI.** `make fixture.transition FIXTURE_ID=<id> TO=<state> REASON=""` is the only non-source-driven path; writes a tracker row + `identity.merge.v1`-style audit topic.
- [ ] **Source-disagreement on lifecycle state.** Two sources reporting conflicting states (one says `live`, another says `postponed`) hold the fixture in `disputed` until quorum (`cfg.fixture_lifecycle_quorum`, default 2 of N) is reached; ops console surfaces the dispute.
