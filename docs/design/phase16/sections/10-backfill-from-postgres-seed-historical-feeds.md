# Phase 16.10 — Backfill from Postgres → seed historical feeds

> Extracted from `docs/planning/ROADMAP.md` §16.10
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.10 Backfill from Postgres → seed historical feeds

**Why this exists:** the swarm cannot migrate to feeds until the feeds *contain* the history the predictors trained on. Live emitter only produces records from "now"; backfill closes the gap.

- [x] `xops/feeds/backfill.py --plane <p> --since <iso> --until <iso> [--source <s>]` reads the unified `match_normalized` table in `cfg.emitter_backfill_batch_size` (default 5000) row chunks, projects each row through the **same writer code path** as live emit (canonical encoder, CRC, sidecar), and writes to a sidecar root `feeds_backfill/` first.
- [x] **Live-emit pause for the partition during promotion** (ledger #19). `xops/feeds/backfill_promote.py` acquires the writer lease for `(plane, source, date_range)`, runs the §16.9 `fsck` against `feeds_backfill/`, then atomically renames partitions into `feeds/` while live emit for that partition is paused; live emit resumes after the rename and writes pointer-stream catch-up envelopes for any wake-ups missed during the pause.
- [x] **Idempotency:** running backfill twice on the same window produces the same output (sha256-identical at the part-file level), assuming the same registry SHA.
- [x] **Backfill rate limit.** `cfg.emitter_backfill_max_rps` (default 1000) caps Postgres read rate so backfill cannot saturate the storage agent; surfaced as `emitter_backfill_rps` gauge.
- [x] **Schema-version selection.** Backfill writes the registry's currently-`active` version for the plane; if both `v1` and `v2` are active it writes both. If a row's source data is incompatible with `v2` (e.g., a dropped enum value), backfill writes only `v1` and emits `proof.flag{kind=backfill_v2_skip}`.
- [x] Proof tests: `test_backfill_idempotent.py`, `test_backfill_promotion_atomic.py`, `test_backfill_pauses_live_emit_for_partition.py`, `test_backfill_respects_writer_lease.py`, `test_backfill_recovers_from_kill.py` (kill mid-batch → resume picks up at the last completed chunk via a Postgres-backed cursor table `feeds_backfill_cursor`), `test_backfill_rate_limited.py`, `test_backfill_writes_all_active_versions.py`.
