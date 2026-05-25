# Phase 16.23 — Chaos & fault injection (NEW; Phase 12 binding)

> Extracted from `docs/planning/ROADMAP.md` §16.23
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.23 Chaos & fault injection (NEW; Phase 12 binding)

- [ ] **Chaos suite under `xops/feeds/chaos/`** (consumed by Phase 12 chaos lane): `chaos_disk_fill.py`, `chaos_kill_writer.py`, `chaos_lease_flap.py`, `chaos_clock_jump.py` (forward jump > 1 h), `chaos_clock_skew.py` (drift +500 ms), `chaos_s3_throttle.py` (return `SlowDown` 50 % of requests), `chaos_pointer_stream_partition.py` (drop 30 % of pointer envelopes), `chaos_corrupt_sidecar.py` (planted bit-flip), `chaos_partial_fsync.py` (truncate last write).
- [ ] **Concurrent reader×writer race.** `test_concurrent_reader_writer_race.py` runs 16 readers and 4 writers for 60 s under chaos; invariant = "no reader observes a missing record OR a duplicate that dedup cannot collapse".
- [ ] **Region-failover drill** (Phase 14 prerequisite, lands as `xfail` here): `chaos_region_failover.py` — primary region becomes unreachable; readers in the surviving region serve stale reads up to `cfg.feeds_cross_region_max_staleness_s` (default 300).
- [ ] Proof tests: `test_chaos_disk_fill_blocks_not_drops.py`, `test_chaos_kill_writer_recovers.py`, `test_chaos_lease_flap_no_double_writer.py`, `test_chaos_clock_jump_does_not_break_rotation.py`, `test_chaos_s3_throttle_circuit_breaks.py`, `test_chaos_pointer_drop_no_data_loss.py`, `test_chaos_corrupt_sidecar_alerts.py`, `test_chaos_partial_fsync_recovered.py`, `test_concurrent_reader_writer_race.py`.
