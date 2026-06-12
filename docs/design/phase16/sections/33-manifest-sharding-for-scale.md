# Phase 16.33 — Manifest sharding for scale (NEW; ledger #37)

> Extracted from `docs/planning/ROADMAP.md` §16.33
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.33 Manifest sharding for scale (NEW; ledger #37)

- [x] **Sharded manifest layout.** `feeds/region=<r>/_manifest/<plane>/<source>/manifest.json` per `(plane, source)`; top-level `feeds/region=<r>/_manifest/index.json` lists all shards with their current sha256.
- [x] **Index rebuild only on topology change.** Adding/removing a `(plane, source)` shard rebuilds the index; routine writes update only the relevant shard. Index uses optimistic-concurrency (`If-Match: <etag>` on S3, file-lock on local disk).
- [x] **Reader walks index then shards.** `FeedReader` reads `index.json` once per `cfg.feeds_index_refresh_s` (default 30) plus on `feeds.pointer.v1` wake-up; per-call shard reads are cached per process.
- [x] **Shard contention test.** `test_concurrent_writers_no_index_contention.py` runs 32 writers for 60 s against a shared index — zero index-rewrite collisions.
- [x] **Migration from monolithic manifest** (one-time): `make feeds.manifest.shard` walks the existing single manifest and splits into shards atomically; original kept as `manifest.json.preshard` for one retention window.
- [x] Proof tests: `test_manifest_sharded_per_plane_source.py`, `test_manifest_index_rebuild_only_on_topology_change.py`, `test_concurrent_writers_no_index_contention.py`, `test_manifest_shard_migration_atomic.py`, `test_index_optimistic_concurrency.py`.
