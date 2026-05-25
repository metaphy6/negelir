# Phase 16.24 — Tenant fairness & multi-tenant isolation (NEW)

> Extracted from `docs/planning/ROADMAP.md` §16.24
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.24 Tenant fairness & multi-tenant isolation (NEW)

> Looks ahead to Phase 20 (per-tenant entitlements). Phase 16 ships the plumbing so per-tenant fair-share is a config flip, not a refactor.

- [ ] **Reader budget per principal.** `cfg.feed_reader_per_principal_qps_max` (default unlimited in Phase 16; per-Phase-20 SKU when monetization enables); enforced by token-bucket in `FeedReader.__init__`. `feed_reader_throttled_total{principal}` counter.
- [ ] **Per-principal connection cap** to the pointer stream: `cfg.feeds_pointer_max_subscribers_per_principal` (default 10).
- [ ] **Snapshot read isolation.** Two principals reading the same `(plane, as_of)` snapshot share a single decoded buffer (decode-once, fan-out) bounded by `cfg.feed_reader_snapshot_buffer_max_mb` (default 256); evicted under LRU; `feed_reader_snapshot_buffer_evictions_total` counter.
- [ ] Proof tests: `test_per_principal_qps_throttled.py`, `test_per_principal_subscriber_cap.py`, `test_snapshot_decode_shared_across_principals.py`.
