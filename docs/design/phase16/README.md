# `docs/design/phase16/` — Phase 16 detail

> **Why this folder exists.** Phase 16 (Emitter & Feed Contract (Production Pivot v3)) grew
> past ROADMAP's review threshold and was carved out into one file
> per sub-section, mirroring the Phase 10 pattern at
> [`../phase10/sections/`](../phase10/sections/). Content here is **binding**
> — the ROADMAP §16 stub is now a pointer that delegates to this
> folder.
>
> **Editing rules.**
> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in
>    the per-section file that owns the item. The ROADMAP §16
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
| §16.0 | [`sections/00-wrong-assumption-ledger.md`](sections/00-wrong-assumption-ledger.md) | Wrong-assumption ledger (retire before any code lands) |
| §16.1 | [`sections/01-feed-contract-registry.md`](sections/01-feed-contract-registry.md) | Feed contract & registry (frozen before any writer code lands) |
| §16.2 | [`sections/02-ndjson.md`](sections/02-ndjson.md) | `FeedWriter` + NDJSON (R3.1–R3.2) |
| §16.3 | [`sections/03-parquet-training-snapshots.md`](sections/03-parquet-training-snapshots.md) | Parquet training snapshots (R3.3) |
| §16.4 | [`sections/04-feedreader.md`](sections/04-feedreader.md) | `FeedReader` (R3.4) |
| §16.5 | [`sections/05-swarm-migration-to-feeds-isolation-gate.md`](sections/05-swarm-migration-to-feeds-isolation-gate.md) | Swarm migration to feeds (R3.4) + isolation gate |
| §16.6 | [`sections/06-live-wake-up-control-plane.md`](sections/06-live-wake-up-control-plane.md) | Live wake-up control plane (`feeds.pointer.v1`) (NEW) |
| §16.7 | [`sections/07-versioned-schema-evolution.md`](sections/07-versioned-schema-evolution.md) | Versioned-schema evolution (R3.5) |
| §16.8 | [`sections/08-storage-backends.md`](sections/08-storage-backends.md) | Storage backends (R3.6) |
| §16.9 | [`sections/09-retention-integrity-sweep-cold-rollup.md`](sections/09-retention-integrity-sweep-cold-rollup.md) | Retention, integrity sweep & cold rollup (R3.7; Phase 14 prerequisite for object-lock) |
| §16.10 | [`sections/10-backfill-from-postgres-seed-historical-feeds.md`](sections/10-backfill-from-postgres-seed-historical-feeds.md) | Backfill from Postgres → seed historical feeds |
| §16.11 | [`sections/11-bus-to-feeds-cutover.md`](sections/11-bus-to-feeds-cutover.md) | Bus-to-feeds cutover (`scrape.raw` / `match.normalized` envelope swap) |
| §16.12 | [`sections/12-per-region-per-league-shard-policy.md`](sections/12-per-region-per-league-shard-policy.md) | Per-region & per-league shard policy (NEW; ledger #18) |
| §16.13 | [`sections/13-tombstones-retractions-cascade-invalidation.md`](sections/13-tombstones-retractions-cascade-invalidation.md) | Tombstones, retractions & cascade invalidation (NEW; ledger #7, #11) |
| §16.14 | [`sections/14-data-classification-propagation-pii-gates.md`](sections/14-data-classification-propagation-pii-gates.md) | Data classification propagation & PII gates (NEW; ledger #12) |
| §16.15 | [`sections/15-reserved-envelope-fields-per-record-signing-groundwork.md`](sections/15-reserved-envelope-fields-per-record-signing-groundwork.md) | Reserved envelope fields & per-record signing groundwork (NEW; ledger #20) |
| §16.16 | [`sections/16-cross-phase-coupling-matrix.md`](sections/16-cross-phase-coupling-matrix.md) | Cross-phase coupling matrix (lint-gated) |
| §16.17 | [`sections/17-observability-slos.md`](sections/17-observability-slos.md) | Observability & SLOs |
| §16.18 | [`sections/18-reliability-disaster-recovery.md`](sections/18-reliability-disaster-recovery.md) | Reliability & disaster recovery |
| §16.19 | [`sections/19-security-access-control.md`](sections/19-security-access-control.md) | Security & access control |
| §16.20 | [`sections/20-performance-budgets-load-testing.md`](sections/20-performance-budgets-load-testing.md) | Performance budgets & load testing |
| §16.21 | [`sections/21-health-liveness-readiness-graceful-shutdown.md`](sections/21-health-liveness-readiness-graceful-shutdown.md) | Health, liveness, readiness & graceful shutdown (NEW; ledger #15) |
| §16.22 | [`sections/22-cost-egress-budgets.md`](sections/22-cost-egress-budgets.md) | Cost & egress budgets (NEW; ledger #16) |
| §16.23 | [`sections/23-chaos-fault-injection.md`](sections/23-chaos-fault-injection.md) | Chaos & fault injection (NEW; Phase 12 binding) |
| §16.24 | [`sections/24-tenant-fairness-multi-tenant-isolation.md`](sections/24-tenant-fairness-multi-tenant-isolation.md) | Tenant fairness & multi-tenant isolation (NEW) |
| §16.25 | [`sections/25-operational-tooling-runbooks.md`](sections/25-operational-tooling-runbooks.md) | Operational tooling & runbooks |
| §16.26 | [`sections/26-producer-idempotency-keys-exactly-once-semantics.md`](sections/26-producer-idempotency-keys-exactly-once-semantics.md) | Producer idempotency keys & exactly-once semantics (NEW; ledger #22) |
| §16.27 | [`sections/27-cross-plane-snapshot-consistency.md`](sections/27-cross-plane-snapshot-consistency.md) | Cross-plane snapshot consistency & `feeds.snapshot.ready.v1` (NEW; ledger #21, #27, #29) |
| §16.28 | [`sections/28-right-to-erasure-surface.md`](sections/28-right-to-erasure-surface.md) | Right-to-erasure (GDPR) surface (NEW; ledger #26) |
| §16.29 | [`sections/29-point-in-time-recovery-manifest-changelog.md`](sections/29-point-in-time-recovery-manifest-changelog.md) | Point-in-time recovery (PITR) & manifest changelog (NEW; ledger #30, #35) |
| §16.30 | [`sections/30-opentelemetry-tracing-across-emit-read.md`](sections/30-opentelemetry-tracing-across-emit-read.md) | OpenTelemetry tracing across emit/read (NEW; ledger #31) |
| §16.31 | [`sections/31-reader-side-caching-bloom-filters-memory-bounds.md`](sections/31-reader-side-caching-bloom-filters-memory-bounds.md) | Reader-side caching, bloom filters & memory bounds (NEW; ledger #23, #28) |
| §16.32 | [`sections/32-compression-strategy-per-plane-dictionaries.md`](sections/32-compression-strategy-per-plane-dictionaries.md) | Compression strategy & per-plane dictionaries (NEW; ledger #36) |
| §16.33 | [`sections/33-manifest-sharding-for-scale.md`](sections/33-manifest-sharding-for-scale.md) | Manifest sharding for scale (NEW; ledger #37) |
| §16.34 | [`sections/34-cross-plane-referential-integrity-guards.md`](sections/34-cross-plane-referential-integrity-guards.md) | Cross-plane referential integrity guards (NEW; ledger #25) |
| §16.35 | [`sections/35-replay-time-travel-for-debugging.md`](sections/35-replay-time-travel-for-debugging.md) | Replay & time-travel for debugging (NEW; ledger #35) |
| §16.36 | [`sections/36-snapshot-delta-mode.md`](sections/36-snapshot-delta-mode.md) | Snapshot delta mode (NEW; ledger #39) |
| §16.37 | [`sections/37-plane-level-circuit-breakers.md`](sections/37-plane-level-circuit-breakers.md) | Plane-level circuit breakers (NEW; ledger #40) |
| §16.38 | [`sections/38-phase-8-schema-fingerprint-coupling.md`](sections/38-phase-8-schema-fingerprint-coupling.md) | Phase 8 schema-fingerprint coupling (NEW; ledger #32) |
| §16.39 | [`sections/39-definition-of-done.md`](sections/39-definition-of-done.md) | Definition of Done |

## Reading order

1. The ROADMAP §16 stub (`docs/planning/ROADMAP.md`) — goal,
   dependencies, and rollup checkbox.
2. The earliest section file relevant to the area you're modifying.
   Later sub-sections often assume earlier ones are in force; if a
   later file's `Depends on` clause names another sub-section,
   re-read it first.
3. The Definition-of-Done sub-section (the one whose title contains
   *Definition of Done* or matching `DoD` rollup) — this is the
   gate that flips the rollup checkbox in ROADMAP.
