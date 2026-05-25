# Phase 16.29 — Point-in-time recovery (PITR) & manifest changelog (NEW; ledger #30, #35)

> Extracted from `docs/planning/ROADMAP.md` §16.29
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.29 Point-in-time recovery (PITR) & manifest changelog (NEW; ledger #30, #35)

- [ ] **Manifest changelog.** Every manifest update appends an entry to `feeds/.changelog/region=<r>/<YYYY-MM-DD>.ndjson` `{ts, manifest_revision, mutation: {kind, plane, source, ...}, sha256_after}`; append-only, fsync per write, daily rotation per writer rules.
- [ ] **Periodic full manifest snapshot** every `cfg.feeds_manifest_snapshot_interval_min` (default 60); snapshot-id = `manifest_revision` at that instant. Restore = pick a snapshot ≤ target, replay changelog forward.
- [ ] **`make feeds.pitr.restore TARGET=<utc-iso> ROOT=<path>`** rebuilds the manifest tree at `TARGET` into `ROOT` without touching the live tree; used by the §16.18 DR drill and by the §16.4 `time_travel(as_of=...)` reader.
- [ ] **Changelog retention** = `cfg.feeds_manifest_changelog_retention_days` (default 90); rotated to cold storage at `cold/.changelog/`.
- [ ] **Rollback semantics documented** (`docs/runbooks/feeds_pitr_runbook.md`): rolling back is non-destructive (target tree is built side-by-side, then atomically swapped under writer-lease pause).
- [ ] Proof tests: `test_pitr_replay_reconstructs_manifest.py`, `test_pitr_to_arbitrary_second_within_retention.py`, `test_changelog_append_only.py`, `test_changelog_round_trip_under_concurrent_writers.py`, `test_pitr_rebuild_is_side_by_side.py`, `test_pitr_outside_retention_refuses.py`.
