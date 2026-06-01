# Phase 13.15 — Reactor isolation & per-league startup quarantine

> Extracted from `docs/planning/ROADMAP.md` §13.15
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.15 Reactor isolation & per-league startup quarantine

- [ ] **One bad league cannot poison others.** A preset that fails to import, a calibration profile with a bad YAML, or a missing mock seed quarantines that league only — the rest stay live (proof test `test_one_bad_league_isolated_at_startup.py`).
- [ ] **Per-league reactor scope.** `LivePredictorReactor` and `TrainerReactor` (Phase 5) carry the `league_id` on every inflight context; a panic in one league's reactor bubbles to that league's DLQ only.
- [ ] **Quarantined leagues surface on the ops console** with a `quarantine_reason` and a `make leagues.unquarantine LEAGUE=<id>` command (writes a tracker row).
- [ ] **DLQ partitioning.** `<topic>.dlq` is keyed on `league_id`; a flooded league does not crowd out others' DLQ entries (cap per league = `cfg.swarm_dlq_max_len_per_league`, default 1 000).
- [ ] **Per-league circuit breaker.** A league that produces > `cfg.league_error_rate_circuit_open` (default 50 % over 5 min) errors trips a circuit breaker; predictions for that league return `503 + X-Reason: league_circuit_open` until the rate recovers below `cfg.league_error_rate_circuit_half_open` (default 5 %); proof test `test_league_circuit_breaker_state_machine.py`.
- [ ] **Quarantine surfaces in catalog GET.** `/v1/catalog` returns `quarantined: true` + `quarantine_reason` for affected rows so frontends can render the right UI state.
- [ ] **Forced-quarantine drill in CI.** `make chaos.league.quarantine LEAGUE=<id>` flips a league into quarantine in a stamped test; asserts other leagues' SLO metrics are unaffected for the duration.
