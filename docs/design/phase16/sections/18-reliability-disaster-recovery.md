# Phase 16.18 — Reliability & disaster recovery

> Extracted from `docs/planning/ROADMAP.md` §16.18
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.18 Reliability & disaster recovery

- [ ] **Manifest rebuild from filesystem.** `make feeds.manifest.rebuild` walks the feeds tree and reconstructs `manifest.json` from on-disk truth (sidecar checksums + parquet footers + NDJSON line-count scan). Exits non-zero if any file is unreferenced or any reference is missing. Required after any restore-from-backup.
- [ ] **Backup / restore drill** (added to `make test.dr` once Phase 14 lands; ships in Phase 16 as the local-disk variant). Procedure: snapshot the feeds volume → wipe → restore → run `feeds.manifest.rebuild` → run `feeds.fsck` → run one predictor parity check against pre-backup output. End-to-end test in CI: `test_restore_drill_local_disk.py`.
- [ ] **Multi-emitter scale-out (scale-symmetry, Rule 5).** N emitter replicas can run simultaneously; each holds the lease for a disjoint subset of `(plane, source)` partitions. Test: `test_two_emitters_partition_cleanly.py` (two emitter processes, half the planes each, no overlapping writes, manifest stays consistent).
- [ ] **Crash recovery proof:** `test_kill_minus_9_loses_at_most_one_record.py` (with `cfg.emitter_fsync_mode=always`, the only loss window is the line currently in the syscall; fsync acks survive a `kill -9` of the writer process).
