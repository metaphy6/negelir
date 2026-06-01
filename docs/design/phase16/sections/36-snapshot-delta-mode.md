# Phase 16.36 — Snapshot delta mode (NEW; ledger #39)

> Extracted from `docs/planning/ROADMAP.md` §16.36
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.36 Snapshot delta mode (NEW; ledger #39)

- [ ] **Delta builder** writes `delta.parquet` files per hour containing only Records whose `idempotency_key` is new vs the prior sealed snapshot, plus tombstones whose `retracted_at` falls in the hour.
- [ ] **Compaction** every `cfg.emitter_snapshot_compaction_hours` (default 24) merges the chain into a fresh `full.parquet`; the delta chain is then pruned.
- [ ] **Reader transparency.** Delta files are joined on read; `manifest.snapshot_chain` records the order. Delta-aware reads are byte-equivalent to the pre-delta full snapshot for the same `(plane, as_of)`.
- [ ] **Disk-savings target** ≥ 60 % vs full mode on the reference workload (binding).
- [ ] Proof tests: `test_delta_snapshot_round_trip.py`, `test_delta_compaction_byte_equivalent_to_full.py`, `test_reader_joins_deltas_transparently.py`, `test_delta_disk_savings_meet_target.py`, `test_delta_chain_pruning_safe.py`.
