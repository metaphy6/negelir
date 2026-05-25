# Phase 16.9 — Retention, integrity sweep & cold rollup (R3.7; Phase 14 prerequisite for object-lock)

> Extracted from `docs/planning/ROADMAP.md` §16.9
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.9 Retention, integrity sweep & cold rollup (R3.7; Phase 14 prerequisite for object-lock)

- [ ] **Per-plane retention** (ledger #17). `make feeds.prune` honours `cfg.feeds_retention_<plane>_ndjson_days` and `cfg.feeds_retention_<plane>_snapshot_days` (defaults: `editorial`=730/3650 for compliance, `market`=30/90 for cost, `score`/`schedule`/`lineup`/`reference`=30/365, `feature_vectors`=14/180, `sec_quarantine`=730/3650, `calibration`=180/3650, `competition`=30/3650, `predict_invalidated`=90/3650). **Refuses to delete** any file whose path is referenced by an active reader cursor (queried via the reactor cursor table from Phase 5 `_base.py`) or that is missing its sidecar checksum.
- [ ] Monthly cold rollup (`cold/<plane>/<YYYY-MM>/<source>.parquet`); rollup verified by snapshot equivalence test before the source NDJSON files are pruned.
- [ ] **Nightly integrity sweep.** `make feeds.fsck` (`xops/feeds/fsck.py`) walks the manifest, recomputes sha256s, verifies sidecars, asserts every NDJSON line round-trips JSON → canonical → JSON byte-equal, asserts every parquet file's footer count equals row count, asserts every record has `captured_at >= file's first day 00:00 UTC`, asserts tombstone targets exist or have been compacted out of retention. Failures → `sec.alert.v1{kind=feeds_integrity_violation, severity=error}`.
- [ ] Proof tests: `test_per_plane_retention_honoured.py`, `test_retention_refuses_to_orphan_active_cursor.py`, `test_cold_rollup_coverage.py`, `test_cold_rollup_byte_equivalent_after_rebuild.py`, `test_fsck_finds_planted_corruption.py`, `test_fsck_detects_orphan_tombstone.py`.
- [ ] `test_object_lock_immutability.py` stays `xfail(reason="phase-14 prerequisite")`.
