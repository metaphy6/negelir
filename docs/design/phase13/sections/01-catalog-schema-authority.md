# Phase 13.1 — Catalog & schema authority (one-time platform work; ships with 13a)

> Extracted from `docs/planning/ROADMAP.md` §13.1
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.1 Catalog & schema authority (one-time platform work; ships with 13a)

- [x] `ai/common/league_catalog.yaml` committed with `schema_version: 1`; matches the shape in `LEAGUE_CATALOG.md` §3.
- [x] `ai/common/league_catalog_loader.py` — pure-Python loader; validates against `ai/common/schemas/league_catalog.schema.json` (JSONSchema 2020-12) at import time; refuses unknown `tier` values, duplicate `league_id`, and dangling `competition_id` references.
- [x] **Catalog is read-only at runtime.** A single module-level `CATALOG: Mapping[str, LeagueRow]` is loaded once and treated as immutable; tests assert no module mutates it.
- [x] **Memoization & footprint.** Loader produces a frozen dict + per-tier index in O(N) once; subsequent lookups are O(1). Catalog with 50 rows must load in ≤ `cfg.league_catalog_load_max_ms` (default 50 ms) on a cold container — tested on the smallest CI lane.
- [x] **Schema versioning.** Bumping `schema_version` requires a migration entry under `xops/leagues/migrations/<from>__to__<to>.py`; lint gates the field name set per version.
- [x] **AST-scan lint** (`xops/lint/no_league_id_branching.py`) refuses any `if league_id == "..."`, `match league_id` literal, or hardcoded league-string comparison anywhere under `ai/`, `swarm/`, or `server/`. Verified by `test_no_league_id_branching.py` — **the cornerstone league-isolation test**, complementary to `test_no_db_imports.py` (Phase 16).
- [x] **Catalog round-trip test.** `test_catalog_roundtrip.py` — load → serialize → diff = empty (whitespace-tolerant); guarantees the YAML is canonical.
- [x] **Catalog ↔ entitlements consistency** (`test_catalog_entitlements_consistency.py`) — every non-T3 row in `league_catalog.yaml` has a matching row in `entitlements.yaml`; missing rows fail CI.
- [x] **Catalog ↔ chart consistency** (`test_catalog_chart_consistency.py`) — every non-T3 row has a `league_<league_id>` key in `xops/versioning/chart.json` ≥ `0.1.0`.
- [x] **Catalog hash anchored in `/healthz`.** Phase 9 `/healthz` exposes `catalog_sha256` (sha256 of canonical YAML bytes); two replicas serving traffic with divergent hashes triggers a Phase 8 alert and — per §13.26 — the lagging replica refuses promotion to `ready`.
- [x] **Reverse index by competition_id.** Loader exposes `BY_COMPETITION: Mapping[str, LeagueRow]` so identity-resolver / emitter / patcher don't iterate the catalog (proof test `test_competition_to_league_o1.py` asserts O(1) lookup under 50-row catalog × 200 competitions).
- [x] **Frozen-set field invariants.** `LeagueRow.competitions`, `aliases`, and `confederation_members` are `frozenset` / tuple at runtime; mutation attempt raises `TypeError` (proof test `test_catalog_immutable.py`).
- [x] **Determinism of YAML load.** Two CI lanes loading the same YAML on different OSes produce identical SHA-256 over the canonicalised in-memory representation (`test_catalog_load_deterministic.py`); rules out dict-ordering or float-precision drift.
- [x] **Catalog GET endpoint** (`/v1/catalog`, admin-token-gated) returns the canonical view + `etag = catalog_sha256`; clients (Phase 8 ops console, Phase 15 frontend) cache against the etag.
