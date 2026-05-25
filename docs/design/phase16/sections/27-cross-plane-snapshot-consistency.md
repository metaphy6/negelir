# Phase 16.27 — Cross-plane snapshot consistency & `feeds.snapshot.ready.v1` (NEW; ledger #21, #27, #29)

> Extracted from `docs/planning/ROADMAP.md` §16.27
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.27 Cross-plane snapshot consistency & `feeds.snapshot.ready.v1` (NEW; ledger #21, #27, #29)

- [ ] **Per-plane ready event** published only after the snapshot manifest update is fsynced (already in §16.3); topic schema lives at `ai/swarm/sdk/schemas/feeds.snapshot.ready.v1.json`.
- [ ] **Joined-snapshot reader API** (already in §16.4): `joined_snapshot(planes, as_of, join_key)` refuses on partial readiness; subscribes to the ready stream when not yet ready.
- [ ] **Cross-plane watermark.** `make feeds.watermark` reports `min(plane_ready_as_of)` per region — the latest `as_of` at which all base planes are jointly ready. Trainers and predictors that span planes use this as their consistent read horizon.
- [ ] **Replay catch-up.** Trainer that subscribes mid-stream may request the last N `ready` events via a Redis `XRANGE` against the stream; cursor format includes the last-consumed `as_of` so re-subscription is idempotent.
- [ ] **Per-region watermark.** When operating multi-region (Phase 14), each region publishes its own `feeds.snapshot.ready.v1` envelope; cross-region joined consumers wait on `min` across required regions.
- [ ] Proof tests: `test_snapshot_ready_event_per_plane.py`, `test_joined_snapshot_refuses_on_partial_readiness.py`, `test_joined_consumer_waits_for_all_planes_ready.py`, `test_watermark_reports_min_across_planes.py`, `test_trainer_replay_catchup_idempotent.py`, `test_per_region_watermark_isolated.py`.
