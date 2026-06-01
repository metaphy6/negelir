# Phase 16.12 — Per-region & per-league shard policy (NEW; ledger #18)

> Extracted from `docs/planning/ROADMAP.md` §16.12
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.12 Per-region & per-league shard policy (NEW; ledger #18)

> Lays the on-disk shape that Phase 13.24 / Phase 14 need from day one.

- [ ] **Region prefix.** Layout becomes `feeds/region=<eu|tr|americas|apac|mea>/(live|snapshots|cold)/<plane>/<source>/...`; `region` is derived from `LeagueRow.data_residency` for league-bound records, or from `cfg.emitter_default_region` (default `eu`) for league-agnostic records (e.g. global reference data).
- [ ] **`region` envelope field.** Every Record carries `region: <r>`; writer refuses a Record whose `region` does not match the partition it would land in (prevents cross-region leak).
- [ ] **Per-league sub-partitioning** (Phase 13.24). Optional `league_id` partition for planes flagged `partition_by_league: true` in the registry (`score`, `schedule`, `lineup`, `market`, `predict_invalidated`); enables per-league backup/restore and per-league deletion (right-to-erasure path is **not** here — that's Phase 9 — but the partition shape must support it).
- [ ] **Cross-region replication descriptor.** `manifest.json` per region carries `replication: {targets: [<r>...], lag_seconds_p99, last_successful_replication_at}`; replication itself is a Phase 14 deliverable, the descriptor ships now so consumers can read it without a schema change later.
- [ ] **Reader region routing.** `FeedReader(region=...)` defaults to `cfg.feeds_reader_default_region` (matches the consumer's deployment region); cross-region reads require `allow_cross_region=True` and emit `feed_reader_cross_region_total` (audit-counted).
- [ ] Proof tests: `test_region_prefix_present_from_day_one.py`, `test_writer_refuses_cross_region_record.py`, `test_per_league_partition_round_trip.py`, `test_reader_default_region_is_local.py`, `test_replication_descriptor_in_manifest.py`.
