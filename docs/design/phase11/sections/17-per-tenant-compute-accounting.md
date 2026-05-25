# Phase 11.17 — Per-tenant compute accounting (Phase 20 hook, dormant by default)

> Extracted from `docs/planning/ROADMAP.md` §11.17
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.17 Per-tenant compute accounting (Phase 20 hook, dormant by default)

> Built but dormant per Phase 20 directive. Flips on the day the
> business charges for compute. No data path is gated when
> `cfg.tenant_quota_enabled=false`.

- [ ] **Tenant attribution.** Every inference call carries an optional `tenant_id` (from the Phase 9 token claims). The router and arbiter propagate it; metrics gain a `tenant_id` label (cardinality bounded by Phase 20 tenant table — never user-id directly).
- [ ] **Energy chargeback.** `negelir_compute_energy_joules_total{tenant_id, device}` and `negelir_compute_seconds_total{tenant_id, device}` accumulate per-tenant; both are computed from §11.9 sources, never fabricated. Sums roll up to the daily quota report (Phase 20).
- [ ] **Per-tenant quotas (lookup-only when dormant).** `cfg.tenant_quota_enabled=false` (default) → counters increment, decisions log "would-allow / would-deny" but never block (matches Phase 20.2 doctrine). When enabled, the arbiter consults the quota before issuing a lease and refuses with `quota_exceeded` (HTTP 429 upstream); rejected requests still log to the would-have audit.
- [ ] **Fairness in the arbiter.** Tenant weights feed the §11.2 weighted-fair-share within a priority tier; one tenant cannot starve others.
