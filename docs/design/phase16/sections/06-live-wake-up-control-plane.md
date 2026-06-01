# Phase 16.6 — Live wake-up control plane (`feeds.pointer.v1`) (NEW)

> Extracted from `docs/planning/ROADMAP.md` §16.6
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.6 Live wake-up control plane (`feeds.pointer.v1`) (NEW)

> Closes ledger #6: live consumers must not poll the manifest.

- [ ] **Pointer stream.** Emitter publishes a tiny envelope `{plane, source, calendar_date, manifest_revision, last_logical_offset, ts}` to the bus topic `feeds.pointer.v1` after every flush (rate-limited to `cfg.emitter_pointer_publish_min_interval_ms`, default 50 ms — one wake-up batches multiple records). Payload size capped at 256 B; topic uses `XSTREAM MAXLEN ~ cfg.feeds_pointer_stream_maxlen` (default 100 000).
- [ ] **Reader subscription.** `FeedReader.stream(...)` subscribes to `feeds.pointer.v1` filtered to its `(plane, sources)` set; on wake-up, advances `logical_offset_records` per the envelope. Without the stream (degraded mode) it falls back to polling at `cfg.feed_reader_poll_interval_ms` (default 1000) and emits `feed_reader_pointer_stream_subscribed=0`.
- [ ] **At-most-once envelope, at-least-once data.** Pointer stream may drop wake-ups under back-pressure; the underlying NDJSON is the source of truth. Reader's correctness does not depend on receiving every pointer — it only depends on receiving *some* pointer eventually OR on the fallback poll firing.
- [ ] **Cross-region wake-up** (Phase 14 prerequisite): pointer stream is per-region; cross-region replication of the data does not fan out wake-ups.
- [ ] Proof tests: `test_pointer_stream_wakes_reader.py`, `test_pointer_stream_drop_does_not_lose_records.py`, `test_reader_falls_back_to_poll_when_stream_unavailable.py`, `test_pointer_envelope_size_bounded.py`, `test_reader_uses_pointer_stream_when_available.py`.
