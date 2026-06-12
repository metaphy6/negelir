# Phase 16.7 — Versioned-schema evolution (R3.5)

> Extracted from `docs/planning/ROADMAP.md` §16.7
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.7 Versioned-schema evolution (R3.5)

- [x] Land a second active version `score.v2` (additive only — exercises §4.2 minor-bump path) and confirm emitter writes both while a `score.v1`-pinned predictor stays green.
- [x] **Registry change-management workflow.** Schema edits go through a PR that runs `make feeds.schema.review` (diffs old vs new, classifies the bump per §4.2, asserts the chart-bump matches). PR body must include the deprecation date for any version flipped to `deprecated`.
- [x] **Deprecation timer.** `make feeds.schema.audit` (CI-nightly) fails when a version has been `deprecated` longer than `cfg.feeds_schema_max_deprecation_days` (default 90) without flipping to `eol`; fails when an `eol` version still has writes recorded in the last 24h.
- [x] **Writer refuses EOL at boot** (ledger #9). Writer process startup loads `registry.json`, refuses to open a writer for any `eol`-marked version, and exits non-zero with a structured error (`error.code=EMITTER_EOL_VERSION_RESURRECTION_BLOCKED`); supervisor pages.
- [x] **Field-removal shadow window.** Per Phase 13 §13 cfg keys, any field removed in a major bump enters a `cfg.field_removal_shadow_days` (default 30) window during which writers still emit it (set to default) and readers tolerate it; lint enforces.
- [x] **Cross-plane alias views.** `match_outcomes.v1` is a virtual plane defined as `score.v1 WHERE status='finished'`; the alias is declared in `registry.json` and materialized by `FeedReader.snapshot(plane="match_outcomes")` without duplicating bytes on disk.
- [x] Proof tests: `test_emitter_writes_all_active_versions.py`, `test_reads_versioned.py`, `test_eol_version_blocks_writes.py`, `test_writer_refuses_eol_version_at_startup.py`, `test_deprecation_timer_fires.py`, `test_field_removal_shadow_window.py`, `test_alias_view_match_outcomes.py`.
