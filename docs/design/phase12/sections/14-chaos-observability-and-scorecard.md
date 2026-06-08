# Phase 12.14 — Chaos observability & resilience scorecard

> Binding per-section detail for Phase 12 §12.14. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A7 (chaos = liveness). **Depends on:** §12.5, §12.13.
> Without this section a chaos run is a pass/fail bit; with it, the
> phase produces **MTTD / MTTR / undetected-attack** signal that proves
> resilience improved, not just that a test ran.

### 12.14 Every chaos run writes a ledger row

A chaos/soak/adversarial run is only useful if it is **measured**.
Phase 12 emits a structured ledger so resilience is trended over time
and regressions are caught.

### 12.14.1 Run ledger schema

- [ ] Each run appends a row to `data/chaos/ledger.jsonl` (PII-clean,
      structural-only — mirrors the Phase 10 §10.32.15 flame-capture
      "no raw input" discipline):
      `{run_id, catalogue_id, layer, target, seed, started_utc,
      injected_fault, expected_signal, observed_signal, detected (bool),
      mttd_ms, mttr_ms, recovery_budget_ms, within_budget (bool),
      resource_drift_pct, verdict ∈ {pass,fail,degraded_as_specified}}`.
- [ ] **`detected`** is the catcher-of-record check (§12.1.2): did the
      expected agent emit the expected `kind`/`degraded_reason`? A
      `detected=false` row is an **undetected-attack/fault** — the
      headline finding of this phase.
- [ ] The ledger is append-only and chaos runs never write user PII into
      it (a lint asserts the schema carries no free-text input field).

### 12.14.2 Resilience scorecard

- [ ] `make chaos.scorecard` renders the ledger into a report
      (`docs/reports/resilience/<date>.md`) with, per owning phase:
      coverage (stubs implemented / total), **undetected count**
      (must be 0 for shipped surfaces), p50/p95 **MTTD** and **MTTR**,
      MTBF from soak (§12.8.2), and the trend vs the last green
      baseline.
- [ ] **MTTD/MTTR budgets are gates.** A scenario that detects too slowly
      (`mttd_ms > cfg.chaos_mttd_budget_ms` for its class) or recovers
      too slowly (`mttr_ms > recovery_budget_ms`, §12.11.2) fails even if
      it eventually recovered.
- [ ] **Trend regression blocks release.** A scorecard where MTTR/MTTD
      regressed beyond `cfg.chaos_trend_regression_pct` vs the last green
      baseline blocks the §12.17 release gate.

### 12.14.3 Degraded-mode catalogue (the contract a chaos test asserts)

- [ ] **Single-source degraded-mode map.** Every degraded contract a
      chaos test asserts (`degraded_reason` enum, the documented HTTP
      triple, the `X-*` headers) is enumerated in
      `docs/testing/degraded_modes.md` (new) and the chaos ledger's
      `expected_signal` is validated against it — a chaos test cannot
      assert an undocumented degraded mode (defeats "I'll just expect
      whatever it does today").
- [ ] This closes the loop with every sister phase's graceful-
      degradation matrix (Phase 9 §9.17 RFC 7807 table, Phase 10 §10.10
      9-row matrix, Phase 11 §11.10 failure modes): each row there is a
      degraded-mode entry here, and each entry has a chaos test that
      drives the system into it.

### 12.14.4 Dashboards & alerts (operator-facing)

- [ ] Chaos/soak metrics export on the existing telemetry plane
      (RED + the Phase 9 §9.8 cardinality discipline — bounded labels,
      no per-entity cardinality); a Grafana panel set
      (`infra/.../dashboards/resilience.json`) shows MTTD/MTTR/coverage.
- [ ] The scorecard's **undetected-attack count > 0** raises a
      build-time alert (not a user-facing one) so a regression in
      detection is impossible to merge silently.

### 12.14.5 Make targets

- [ ] `make chaos.scorecard` (render report from ledger),
      `make chaos.ledger.verify` (schema + no-PII lint on the ledger),
      `make chaos.trend` (compare to last green baseline) — dispatched
      via `xops/makefile/chaos.py`.
- [ ] The §12.17 DoD requires the latest scorecard attached to the
      release with **zero undetected** for every shipped owning phase
      and MTTD/MTTR within budget.
