# Phase 16.38 — Phase 8 schema-fingerprint coupling (NEW; ledger #32)

> Extracted from `docs/planning/ROADMAP.md` §16.38
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.38 Phase 8 schema-fingerprint coupling (NEW; ledger #32)

- [ ] **Subscription.** Writer subscribes to `schema.fingerprint.changed.v1{plane, source, old_sha, new_sha}` (Phase 8 source-watcher topic); on event, the writer for `(plane, source)` **pauses** and sets `/healthz/ready=503` until either:
  - operator ACK via `make feeds.fingerprint.ack PLANE=... SOURCE=... NEW_SHA=...` (logged), or
  - patcher (Phase 17) lands an extractor patch and emits `schema.fingerprint.promoted.v1{plane, source, sha}`.
- [ ] **No silent emit during pause.** Records arriving during pause go to the producer SDK's bounded retry queue (`cfg.emitter_fingerprint_pause_max_records`, default 10 000); overflow → quarantine with `reason=fingerprint_pause_overflow`.
- [ ] **Audit chain.** Every fingerprint event + ACK + promotion is recorded in `audit.feeds.v1{kind=fingerprint_event}`; chain-broken on missing entries (read by `make feeds.fingerprint.audit`).
- [ ] Proof tests: `test_schema_fingerprint_pauses_writer.py`, `test_writer_resumes_after_operator_ack.py`, `test_writer_resumes_after_patcher_promotion.py`, `test_fingerprint_pause_queue_bounded.py`, `test_fingerprint_audit_chain_intact.py`.
