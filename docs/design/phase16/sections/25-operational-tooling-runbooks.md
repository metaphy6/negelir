# Phase 16.25 — Operational tooling & runbooks

> Extracted from `docs/planning/ROADMAP.md` §16.25
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.25 Operational tooling & runbooks

- [x] Make targets: `make feeds.up`, `make feeds.down`, `make feeds.tail PLANE=... SOURCE=...`, `make feeds.snapshot.rebuild`, `make feeds.prune`, `make feeds.fsck`, `make feeds.manifest.rebuild`, `make feeds.parity`, `make feeds.schema.review`, `make feeds.schema.audit`, `make feeds.backfill`, `make feeds.backfill.promote`, `make feeds.chaos.run TEST=...`, `make feeds.cost.report`, `make feeds.region.replicate FROM=eu TO=tr` (Phase 14 stub), `make feeds.signing.dryrun` (Phase 17 stub), `make feeds.tombstone.audit`. Each dispatches via `xops/feeds/*.py` per [`xops/README.md`](../../xops/README.md) conventions.
- [x] Runbooks under `docs/runbooks/`: `feeds_cutover_rollback.md`, `feeds_disk_full.md`, `feeds_lease_flapping.md`, `feeds_corruption_recovery.md`, `feeds_backfill_procedure.md`, `feeds_restore_from_backup.md`, `feeds_writer_recovery.md`, `feeds_parity.md`, `feeds_tombstone_semantics.md`, `feeds_clock_skew.md`, `feeds_pointer_stream_outage.md`, `feeds_region_failover.md` (Phase 14 stub), `feeds_cost_overrun.md`, `feeds_schema_evolution.md`, `feeds_pii_quarantine.md`, `feeds_chaos_runbook.md`. Each runbook ends with a "test this runbook" section that maps to a CI test name.
- [x] **`xops/versioning/chart.json`** new keys (Pivot v3 placement): `datasource_emitter` (component), `common_feeds` (component for the reader library + schema registry). Both bumped to ≥ `1.0.0` at end of phase.
- [x] **`xops/env/.env.example`** documents every new key (full enumeration in §16.39 DoD).
