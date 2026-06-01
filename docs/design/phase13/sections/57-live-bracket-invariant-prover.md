# Phase 13.57 — Live bracket invariant prover

> Extracted from `docs/planning/ROADMAP.md` §13.57
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.57 Live bracket invariant prover

> Retires assumption §13.0 #69. A bracket is correct at draw time;
> it must remain correct under every fixture lifecycle event.

- [ ] **Invariants enforced.** (a) Round N entrant count = Round N-1 qualifier count; (b) no `stable_id` in two simultaneous bracket slots; (c) no slot empty after `Stage.draw_completed_at + cfg.bracket_slot_resolve_max_h`; (d) seeds respect `Competition.seeding_rules` (e.g. UCL avoids same-association in group draw).
- [ ] **Invariant prover trigger.** Runs on every `fixture.lifecycle.v1`, every `cascade.fan_out.v1`, every §13.40.5 retroactive sanction; failure emits `bracket.invariant_violated.v1{competition_id, stage_id, invariant, observed, expected}`.
- [ ] **Publish gate.** A violated invariant blocks publish for every fixture in the affected stage until cleared (proof test `test_invariant_violation_blocks_publish.py`).
- [ ] **Drill.** `make chaos.bracket.violate COMPETITION=<id>` injects a synthetic violation; recovery via federation-published correction must clear the gate within `cfg.bracket_violation_recovery_max_h` (default 12 h).
- [ ] **Determinism of prover.** Same fixture-history input → same violation set; proof test `test_invariant_prover_deterministic.py`.
