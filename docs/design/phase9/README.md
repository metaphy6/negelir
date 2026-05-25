# `docs/design/phase9/` — Phase 9 detail

> **Why this folder exists.** Phase 9 (Go REST API & Identity (Public Surface)) grew
> past ROADMAP's review threshold and was carved out into one file
> per sub-section, mirroring the Phase 10 pattern at
> [`../nlp/sections/`](../nlp/sections/). Content here is **binding**
> — the ROADMAP §9 stub is now a pointer that delegates to this
> folder.
>
> **Editing rules.**
> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in
>    the per-section file that owns the item. The ROADMAP §9
>    stub carries only the phase-rollup checkbox.
> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs
>    LEVEL=minor NOTE="..."` in the same commit (per AGENTS.md §6.1).
> 3. Cross-phase references are authoritative against
>    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the
>    matching `docs/design/*.md` anchors. Fix this folder if a claim
>    drifts — never silently re-plan a sister phase.
> 4. No rename of these files without explicit human request (URL
>    stability); no deletion of a binding `[ ]` item; no weakening
>    of a Definition-of-Done gate.

## Layout

| Source | File | Theme |
|---|---|---|
| §9.0 | [`sections/00-forward-phase-cross-phase-alignment.md`](sections/00-forward-phase-cross-phase-alignment.md) | Forward-phase + cross-phase alignment |
| §9.1 | [`sections/01-surface-full-route-table-semantics.md`](sections/01-surface-full-route-table-semantics.md) | Surface (v1) — full route table + semantics |
| §9.2 | [`sections/02-identity-sessions-and-key-lifecycle.md`](sections/02-identity-sessions-and-key-lifecycle.md) | Identity, sessions, and key lifecycle |
| §9.3 | [`sections/03-request-flow.md`](sections/03-request-flow.md) | Request flow (RPC pattern, idempotency, cache-first, cancellation) |
| §9.4 | [`sections/04-openapi-source-of-truth-handler-generation.md`](sections/04-openapi-source-of-truth-handler-generation.md) | OpenAPI source-of-truth + handler generation |
| §9.5 | [`sections/05-wire-authority-additions-schemas-envelope-discipline.md`](sections/05-wire-authority-additions-schemas-envelope-discipline.md) | Wire-authority additions, schemas, envelope discipline |
| §9.6 | [`sections/06-phase-7-sec-gate-wiring.md`](sections/06-phase-7-sec-gate-wiring.md) | Phase-7 sec gate wiring (the integration tier §7.7 deferred) |
| §9.7 | [`sections/07-rate-limiting-quotas-denylist.md`](sections/07-rate-limiting-quotas-denylist.md) | Rate limiting, quotas, denylist |
| §9.8 | [`sections/08-observability-red-metrics-structured-logs-audit.md`](sections/08-observability-red-metrics-structured-logs-audit.md) | Observability — RED metrics, structured logs, audit |
| §9.9 | [`sections/09-idempotency-cache-backpressure.md`](sections/09-idempotency-cache-backpressure.md) | Idempotency, cache, backpressure (deeper than §9.3) |
| §9.10 | [`sections/10-deployment-mtls-bootstrap-secret-rotation.md`](sections/10-deployment-mtls-bootstrap-secret-rotation.md) | Deployment, mTLS bootstrap, secret rotation |
| §9.11 | [`sections/11-versioning-deprecation-sunset-policy.md`](sections/11-versioning-deprecation-sunset-policy.md) | Versioning, deprecation, sunset policy |
| §9.12 | [`sections/12-triangle-test-cfg-knobs.md`](sections/12-triangle-test-cfg-knobs.md) | Triangle test & cfg knobs (mandatory) |
| §9.13 | [`sections/13-definition-of-done.md`](sections/13-definition-of-done.md) | Definition of Done (binding — mirrors §8.9 density) |
| §9.14 | [`sections/14-proof-tests.md`](sections/14-proof-tests.md) | Proof tests (≥ 60 deterministic + 15 adversarial; mirrors §8.16 density) |
| §9.15 | [`sections/15-forward-phase-contracts.md`](sections/15-forward-phase-contracts.md) | Forward-phase contracts (do NOT break later phases) |
| §9.16 | [`sections/16-versioning-addendum.md`](sections/16-versioning-addendum.md) | Versioning addendum |
| §9.17 | [`sections/17-performance-hardening-resilience-patterns.md`](sections/17-performance-hardening-resilience-patterns.md) | Performance hardening & resilience patterns (binding) |

## Reading order

1. The ROADMAP §9 stub (`docs/planning/ROADMAP.md`) — goal,
   dependencies, and rollup checkbox.
2. The earliest section file relevant to the area you're modifying.
   Later sub-sections often assume earlier ones are in force; if a
   later file's `Depends on` clause names another sub-section,
   re-read it first.
3. The Definition-of-Done sub-section (the one whose title contains
   *Definition of Done* or matching `DoD` rollup) — this is the
   gate that flips the rollup checkbox in ROADMAP.
