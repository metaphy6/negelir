# Phase 13.64 — Catalog uniqueness constraints

> Extracted from `docs/planning/ROADMAP.md` §13.64
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.64 Catalog uniqueness constraints

> Retires assumption §13.0 #76.

- [ ] **Unique-key set.** Loader refuses on duplicate of any: `league_id`, `(legal_name, country)`, `(display_name, country)`, `federation_canonical_url`, `(competition_id)` across all leagues.
- [ ] **Alias collision check.** A league's `aliases[]` must not collide with another league's `display_name` or `aliases[]` *within the same country*; cross-country collisions allowed but emit a `proof.flag.v1{kind=cross_country_alias_collision}` for NLP review (proof test `test_catalog_alias_collision_within_country.py`).
- [ ] **Stable-id collision.** Across all leagues' `Team` records, no two `stable_id` may carry the same `(legal_name, country, founded_year)` triple; collision triggers manual identity review per §13.4.
- [ ] **Migration-time uniqueness check.** `make leagues.catalog.validate` runs the constraint set; CI green-gate.
- [ ] **Lint.** `xops/lint/catalog_uniqueness.py` runs on every YAML diff.
