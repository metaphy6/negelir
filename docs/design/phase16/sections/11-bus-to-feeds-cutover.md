# Phase 16.11 — Bus-to-feeds cutover (`scrape.raw` / `match.normalized` envelope swap)

> Extracted from `docs/planning/ROADMAP.md` §16.11
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.11 Bus-to-feeds cutover (`scrape.raw` / `match.normalized` envelope swap)

- [ ] **Dual-write window** of `cfg.emitter_dual_write_days` (default 14): `scrape.raw` and `match.normalized` topics carry **both** the inline payload (`v1`) and the new feed-pointer envelope (`v2`) per message; consumers opt into v2 via subscription option `prefer_version="v2"`.
- [ ] **Consumer migration order:** (1) categorizer, (2) processor, (3) storage, (4) proofreader replicas, (5) swarm read paths. Each consumer must demonstrate 24 h of v2-only consumption with zero v1 fallback before the v1 publisher is removed.
- [ ] **Rollback plan documented** in `docs/runbooks/feeds_cutover_rollback.md`: how to flip a consumer back to v1, how to backfill a missed v1→v2 window, what the SLO impact is per minute of rollback.
- [ ] **Cutover guard test** `test_dual_write_payload_equivalent.py`: for every message published during dual-write, the v1 inline payload and the bytes pointed to by the v2 envelope's `(ndjson_path, byte_range, sha256)` must hash identically.
- [ ] **Removal gate:** v1 publish path stays code-resident behind `cfg.emitter_publish_v1 = on|off` (default `on` until cutover complete; flipped to `off` per environment, gated on the §18 isolation tests being green for that env's swarm).
