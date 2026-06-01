# Phase 16.34 — Cross-plane referential integrity guards (NEW; ledger #25)

> Extracted from `docs/planning/ROADMAP.md` §16.34
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.34 Cross-plane referential integrity guards (NEW; ledger #25)

- [ ] **Rolling xref index.** Writer maintains an in-memory rolling index of `schedule.stable_id` per region (TTL = `cfg.emitter_xref_window_h`, default 168 h = 7 d) backed by a Redis hash for cross-process consistency.
- [ ] **Orphan detection.** A `lineup`/`market`/`score` Record whose `match_stable_id` is absent from the active index is **quarantined** with `reason=ref_integrity_violation`, NOT dropped.
- [ ] **Late-arrival promotion.** When a `schedule` Record arrives for a previously-missing `match_stable_id`, the writer rescans recent quarantine and **promotes** matching orphans into the live partition within `cfg.emitter_xref_promotion_max_s` (default 300 s); promotion preserves original `captured_at`, `idempotency_key`, and `trace_context`.
- [ ] **Adversarial corpus.** `xops/feeds/corpora/xref/` includes (a) lineup-without-schedule, (b) lineup-with-late-schedule, (c) lineup-with-permanently-missing-schedule (after grace, escalates to `proof.flag{kind=permanent_orphan}` + tombstone the orphan).
- [ ] Proof tests: `test_orphan_lineup_quarantined.py`, `test_xref_index_ttl_honoured.py`, `test_late_schedule_promotes_quarantined_lineup.py`, `test_permanent_orphan_eventually_tombstoned.py`, `test_xref_index_consistent_across_writer_replicas.py`.
