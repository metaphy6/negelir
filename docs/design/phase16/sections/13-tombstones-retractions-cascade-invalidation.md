# Phase 16.13 — Tombstones, retractions & cascade invalidation (NEW; ledger #7, #11)

> Extracted from `docs/planning/ROADMAP.md` §16.13
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.13 Tombstones, retractions & cascade invalidation (NEW; ledger #7, #11)

> Closes the long-standing gap that EMITTER §6 #4 ("no in-place edits") opened: how does corrected data ever propagate?

- [ ] **Tombstone Record shape.** `{tombstone: true, stable_id, retracted_at, reason: enum, correction_stable_id?: str}` written to the same `(plane, source, date)` NDJSON as a normal append. Required envelope fields keep their meaning; `payload` carries `{reason_detail: str}`.
- [ ] **`record.retracted` bridge.** Phase 6 freshness emits `freshness.events.v1{kind=record_retracted, stable_id, plane, source, reason}`; emitter subscribes and writes the corresponding tombstone to the matching plane's NDJSON within `cfg.emitter_tombstone_propagation_max_s` (default 5).
- [ ] **Snapshot effect** (already in §16.3): tombstones are applied at watermark-close; the `match_outcomes` alias view excludes tombstoned outcomes.
- [ ] **Cascade invalidation feed** (Phase 13.51). Emitter subscribes to `predict.invalidated.v1` on the bus and **dual-writes**: the bus carries the wake-up envelope, the feed `feeds/.../predict_invalidated.v1/...` carries the persisted log. Single transactional barrier: bus publish fails if feed write fails, and vice-versa.
- [ ] **Trainer impact documented** in `docs/runbooks/feeds_tombstone_semantics.md`: how to read a snapshot with vs without tombstone application; how to backfill a model that was trained against pre-tombstone data.
- [ ] Proof tests: `test_tombstone_round_trip.py`, `test_freshness_retraction_creates_tombstone_within_grace.py`, `test_predict_invalidated_dual_write.py`, `test_predict_invalidated_dual_write_atomic.py` (one fails → both rolled back), `test_snapshot_excludes_tombstoned_stable_ids.py`, `test_match_outcomes_alias_excludes_tombstones.py`.
