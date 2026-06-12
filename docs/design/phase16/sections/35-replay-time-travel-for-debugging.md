# Phase 16.35 — Replay & time-travel for debugging (NEW; ledger #35)

> Extracted from `docs/planning/ROADMAP.md` §16.35
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.35 Replay & time-travel for debugging (NEW; ledger #35)

- [x] **Reader API** (already in §16.4): `FeedReader.time_travel(as_of=T)` returns a reader bound to `(manifest_revision, registry_sha, tombstone_set)` as observed at wall-clock `T`.
- [x] **CLI** `make feeds.replay PRINCIPAL=swarm.predictor.elo AS_OF=2026-04-19T19:32:14Z PLANE=score SAMPLES=100` reproduces what that principal would have seen at that time, with sha256 of the first record matching (deterministic).
- [x] **Trace-driven replay.** Given an OTEL traceparent, `make feeds.replay.trace TRACEPARENT=00-...` reconstructs the read window from the spans and replays it; used by Phase 17 patcher's diagnostic bundle.
- [x] **Audit binding.** Replay requests for non-`public` data are logged in `audit.feeds.v1{kind=replay}` with operator identity.
- [x] Proof tests: `test_time_travel_excludes_post_t_tombstones.py`, `test_time_travel_uses_contemporaneous_registry.py`, `test_time_travel_manifest_revision_is_deterministic.py`, `test_replay_cli_byte_stable.py`, `test_replay_trace_reconstructs_read_window.py`.
