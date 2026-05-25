# Phase 16.37 — Plane-level circuit breakers (NEW; ledger #40)

> Extracted from `docs/planning/ROADMAP.md` §16.37
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.37 Plane-level circuit breakers (NEW; ledger #40)

- [ ] **Per-`(plane, source)` quarantine-rate breaker.** Window `cfg.emitter_circuit_quarantine_window_s` (default 60); threshold `cfg.emitter_circuit_quarantine_threshold` (default 0.30 = 30 %); on trip, all inbound for that `(plane, source)` is rejected with `proof.flag{kind=circuit_open}` and the breaker pages.
- [ ] **Half-open recovery.** `cfg.emitter_circuit_half_open_s` (default 300); single test record allowed; success closes, failure re-opens with exponential backoff capped at `cfg.emitter_circuit_max_open_s` (default 3600).
- [ ] **Per-plane quarantine quota.** `cfg.emitter_quarantine_max_pct_per_h` (default 5 %) — if over a rolling hour > 5 % of total inbound was quarantined, breaker opens regardless of rate.
- [ ] **Manual override.** `make feeds.circuit.close PLANE=score SOURCE=nesine` (operator action; logged to `audit.feeds.v1{kind=circuit_manual_close}`).
- [ ] Proof tests: `test_circuit_opens_on_quarantine_storm.py`, `test_circuit_half_open_recovers.py`, `test_circuit_isolated_per_source.py`, `test_circuit_quota_independent_of_rate.py`, `test_circuit_manual_close_audited.py`, `test_circuit_exponential_backoff_capped.py`.
