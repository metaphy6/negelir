# Phase 16.26 — Producer idempotency keys & exactly-once semantics (NEW; ledger #22)

> Extracted from `docs/planning/ROADMAP.md` §16.26
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.26 Producer idempotency keys & exactly-once semantics (NEW; ledger #22)

> Closes the long-standing dedup gap where retried scrapes with different `captured_at` defeated `(stable_id, captured_at)` keying.

- [x] **Idempotency-key SDK helper.** `common.feeds.canonical.idempotency_key(payload: Mapping) -> str` returns `sha256(canonical_payload_bytes)`; emitter producer SDK fills it automatically when not supplied.
- [x] **Writer-side rejection on missing key** — record refused with `EMITTER_MISSING_IDEMPOTENCY_KEY`; lint blocks producer code that bypasses the helper.
- [x] **Cross-process dedup** via Redis bloom filter `emitter:idem:<plane>:<source>` (m sized for `cfg.emitter_idempotency_bloom_size`, default 10⁶ entries × FPR 1 %), TTL `cfg.emitter_idempotency_dedup_window_s` (default 600).
- [x] **Reader-side dedup** keys on `(stable_id, idempotency_key)` not `(stable_id, captured_at)`.
- [x] **Replayability proof.** `test_replay_same_records_no_duplicates.py` — a producer replays the same Records 5× through a clean writer; on-disk record count equals 1× input count, all 4× extras counted in `emitter_idempotency_dedup_total`.
- [x] Proof tests: `test_idempotency_key_collapses_retries.py`, `test_writer_refuses_record_without_idempotency_key.py`, `test_idempotency_bloom_ttl_expires.py`, `test_idempotency_helper_stable_across_python_versions.py`.
