# Phase 13.22 — Disaster recovery: per-league backup / restore

> Extracted from `docs/planning/ROADMAP.md` §13.22
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.22 Disaster recovery: per-league backup / restore

> Retires assumption §13.0 #23.

- [ ] **Per-league backup partition.** Postgres logical-replication slots + Phase 16 emitter NDJSON shards keyed on `league_id`; `make leagues.backup LEAGUE=<id>` produces a self-contained tarball.
- [ ] **Per-league restore drill.** `make leagues.restore LEAGUE=<id> FROM=<tarball>` restores into a staging schema, runs `make leagues.readiness LEAGUE=<id>` against the restored state, refuses to swap into prod unless the report is `pass`.
- [ ] **Quarterly DR rehearsal.** CI runs `make leagues.dr.rehearse LEAGUE=<id>` against a synthetic disaster (corrupt one league's records); restoration must complete within `cfg.league_rto_max_minutes` (default 60) and lose no events older than `cfg.league_rpo_max_minutes` (default 5).
- [ ] **Cross-league corruption isolation.** Corrupting one league's records (intentional injection) does not affect any other league's read path or restore time (proof test `test_dr_cross_league_isolation.py`).
