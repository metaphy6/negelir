# Phase 13.3 — Per-league preset discipline + scaffolding

> Extracted from `docs/planning/ROADMAP.md` §13.3
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.3 Per-league preset discipline + scaffolding

- [x] **One file per league.** `ai/common/leagues/<league_id>.py` exposes a single `CONFIG: LeagueConfig` constant (LEAGUE_CATALOG.md §6.1).
- [x] **Aggregator** `ai/common/leagues/__init__.py` builds `LEAGUE_CONFIGS = {…}` lazily; **a typo or import error in one preset must not break others** — the aggregator wraps each import in a try / on-fail records `negelir_league_preset_load_failed_total{league_id, reason}` and refuses to expose the broken row (proof test `test_one_bad_preset_does_not_break_others.py`).
- [x] **Backwards-compat gate.** Every new `LeagueConfig` field has a default; `test_all_existing_presets_load.py` triangle-tests every preset against the latest field set.
- [x] **Structural-only lint** (`xops/lint/league_preset_static.py`) — refuses `LeagueConfig` fields whose values are computed (`os.environ`, function calls, list comprehensions over external state). Presets carry team rosters / format / derbies / aliases — never Elo tables, calibration tables, or anything else that should live in Postgres.
- [x] **Scaffold tooling.** `make league.scaffold LEAGUE_ID=<id> COUNTRY=<iso> CONFEDERATION=<x>` generates the preset file + a stub mock-seed manifest + a tracker row + a chart-key bump in one step.
- [x] **Linters refuse string-list duplication.** Team-name aliases live in `Team` records (Reference plane), not in the preset; lint refuses `aliases=[...]` of length > 0 inside `LeagueConfig`.
- [x] **Preset checksum.** Each preset module exposes `CONFIG_SHA256: str`; mismatch between declared and computed sha (over canonical `dataclasses.asdict`) fails `test_preset_checksum.py`. Used by §13.21 audit log to detect silent edits.
- [x] **Preset import isolation.** Preset modules are imported in a sandboxed namespace (no `from ai.swarm import *`, no DB calls at import time); `xops/lint/league_preset_static.py` extends to forbid these imports. Proof test `test_preset_no_side_effects.py` imports each preset under a faulted DB connection and expects success.
- [x] **Preset-import budget.** Total wall-clock to import all `LEAGUE_CONFIGS` for the catalog (50 rows) ≤ `cfg.league_preset_total_import_max_ms` (default 300 ms) on the smallest CI lane; soak `bench/preset_import.py`. Per §13.9 lazy preset import keeps the cold-start path under Phase 11 §11.0 budget.
- [x] **Concurrent-import safety.** Two reactor processes importing the same preset simultaneously (cold scaler add + cold reactor restart) must not produce a `partially-initialised module` race; loader uses an import-lock; proof test `test_preset_concurrent_import_safe.py`.
- [x] **Preset-removal safety.** Removing a preset file in a commit refuses CI unless: (a) the catalog row is also deleted; (b) every dependent row in `entitlements.yaml` is removed; (c) the §13.21 audit row is signed; (d) historical fixture references resolve via the audit-ledger time-travel (§13.42).
