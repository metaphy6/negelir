# Phase 9.15 — Forward-phase contracts (do NOT break later phases)

> Extracted from `docs/planning/ROADMAP.md` §9.15
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.15 Forward-phase contracts (do NOT break later phases)

- [ ] **Phase 10 (NLP).** `/v1/qa` request body `{q, locale}` is closed for v1; Phase 10 humanizer adds `humanize: bool` (default false) — additive minor bump. The qa handler MUST stamp `qa_correlation_id` (per §8.16.12) on every spawned `predict.request.v1`; boundary test guards.
- [ ] **Phase 11 (compute).** API container is `cfg.compute_class=cpu_only`; cgo build tags exclude CUDA. Boundary: `cmd/api/main.go` build-tagged `//go:build cpu_only`.
- [ ] **Phase 12 (chaos).** New chaos catalogue stubs land alongside §9.13: `chaos-api-redis-flap` (assert 503 not 5xx panic), `chaos-api-pg-drop` (assert health degrades gracefully — readyz turns red, livez stays green), `chaos-api-bus-flood` (assert backpressure mode engages), `chaos-api-jwt-key-purge-mid-request` (assert in-flight requests with retired kid still complete), `chaos-api-half-replica-kill` (assert N-1 replicas continue serving + reply-stream reaper sweeps orphans).
- [ ] **Phase 13a (catalog).** `profile_id = league_id` resolution lives in ONE function `internal/api/profile.go::ResolveProfileID(leagueID)`; Phase 13a swap to catalog-driven changes the body of this one function with no handler diff. Boundary test: every place a profile_id is stamped on a bus envelope routes through this function (AST scan).
- [ ] **Phase 14 (K8s).** API replicas:N proven at chaos N=3; `consensus.v1` MUST stay replicas:1 (per §5.3 single-publication guarantee). Phase 9 readyz probe explicitly tolerates `consensus.v1` not being co-located.
- [ ] **Phase 16 (Emitter).** API reads through `CalibrationStore` Protocol (per §5 forward block); swapping the in-memory backend for the Phase 16 feed-plane backend changes 0 handler lines. Boundary test: `internal/handlers/predictions.go` imports the Protocol interface, never the concrete impl.
- [ ] **Phase 19 (GA).** SLO burn-rate alerts (§9.8) drive the GA gate. `make api.slo-report` produces a 28-day rolling SLO summary; GA blocks if availability < 99.5% or p95 outside budget.
- [ ] **Phase 20 (monetization).** Tier enforcement is dormant flag-only at this phase; `tier_quota.go` middleware ships unloaded behind `cfg.api_tier_enforcement_enabled=false`. Phase 20 flips the flag, lands the `tiers` catalog rows, and adds Stripe webhooks at `/v1/billing/*` (NEW routes — do NOT pre-expose). Boundary: no `/v1/billing/*` route exists in v1.
