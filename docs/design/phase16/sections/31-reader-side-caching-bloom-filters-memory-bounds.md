# Phase 16.31 — Reader-side caching, bloom filters & memory bounds (NEW; ledger #23, #28)

> Extracted from `docs/planning/ROADMAP.md` §16.31
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.31 Reader-side caching, bloom filters & memory bounds (NEW; ledger #23, #28)

- [ ] **Per-process snapshot LRU** (decoded chunks keyed by `(plane, as_of, day, part_id, columns_hash)`); size cap `cfg.feed_reader_snapshot_cache_max_mb` (default 1024). Eviction surfaces `feed_reader_snapshot_cache_evictions_total`.
- [ ] **Bloom sidecar consumption** (paired with §16.3): reader checks `<part>.bloom` before any point-lookup; bloom miss = guaranteed absence (zero false negatives).
- [ ] **Memory governor** binding (Phase 11 §11.3): reader claims `cfg.feed_reader_memory_budget_mb` (default 768) and any allocation that would exceed the budget refuses with `error.code=FEED_READER_MEMORY_BUDGET_EXCEEDED` rather than OOM-killing the process.
- [ ] **Cache invalidation on tombstone.** Reader subscribes to `freshness.events.v1{kind=record_retracted}` and invalidates affected snapshot cache entries within `cfg.feed_reader_cache_invalidation_max_s` (default 5).
- [ ] Proof tests: `test_snapshot_lru_cache_reduces_redecodes.py`, `test_bloom_lookup_zero_false_negatives.py`, `test_bloom_fpr_within_budget.py`, `test_memory_governor_refuses_over_budget.py`, `test_snapshot_streams_under_memory_cap.py`, `test_cache_invalidation_on_tombstone.py`.
