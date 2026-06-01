# Phase 8.6 — Internal schema-drift sentinel (`maint.schema.v1`)

> Extracted from `docs/planning/ROADMAP.md` §8.6
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 8.6 Internal schema-drift sentinel (`maint.schema.v1`)

> **Re-scoped from the original §8.1.** Scraper-selector healing moved to Phase 17 patcher (`extractor`/`schema` scopes). What stays here: detect drift between (a) JSON Schemas in `ai/swarm/sdk/schemas/` and live payloads on the bus, (b) Postgres column sets vs the migration-derived expected set, (c) `payloads.py` dataclass shape vs the matching JSON Schema. Phase 8 detects + reports; humans (or Phase 17 patcher under `migration` scope) fix.
> K8s/compose deployment resources → [`docs/design/MAINT_DEPLOYMENT_CATALOGUE.md`](../docs/design/MAINT_DEPLOYMENT_CATALOGUE.md).

- [x] **Detector A — payload vs schema.** Tap `telemetry.v1`'s sample stream (Phase 4.6 already mirrors a configurable %); for each sampled envelope, run `swarm.sdk.schemas.validate(topic, payload)`. On mismatch → `maint.event.v1{kind=schema_drift_detected, target=<topic>, errors[], sample_envelope_id}` (debounced per `(topic, error_signature)` for `cfg.maint_schema_debounce_s`, default 3600). Sample rate is `cfg.maint_schema_sample_rate` (default 0.01) — full validation is not free; trades coverage for CPU.
- [x] **Detector B — Postgres column drift.** Once per `cfg.maint_schema_pg_check_interval_s` (default 1h), run `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public'`, compare to the expected set derived from `migrations/*.sql` parsing. Drift → same `kind=schema_drift_detected, target=<table>`. The migration parser uses `sqlglot` (already a candidate dep for Phase 17 patcher) when available, falling back to a tolerant regex parser that handles `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN`, and inline `CHECK` constraints. **False-positive guard:** the parser tracks `unknown_constructs` (e.g. `CREATE FUNCTION`, partial-index `WHERE`); when a table's expected column set was assembled with any unknown_constructs in scope, a drift event for that table is downgraded to `severity=info` (not `warn`) and prefixed `parser_uncertain:` so an operator can distinguish parser failure from real drift.
- [x] **Detector C — dataclass vs schema.** AST scan at startup asserts every `@dataclass` in `payloads.py` has a matching JSON Schema with the same field set + types. **Scope of failure:** drift fails the *Phase 8 schema-sentinel agent* startup only (loud `SystemExit(1)` from the agent module's `__main__`); other agents in the registry are not killed. The Supervisor emits `sec.alert.v1{kind=schema_drift_detected, severity=critical}` for the missing agent. This contains the blast radius — code/schema drift is a release-time bug for one tracked surface, not a swarm-wide outage.
- [x] **Out of scope (binding).**
  - **Auto-derive selectors / extractors** — Phase 17 patcher only.
  - **Auto-apply migrations** — humans only. The sentinel emits the event; nothing in v1 runs `psql -f migrations/NNN_*.sql` unattended. (`cfg.maint_schema_auto_apply_enabled` exists in config for forward compatibility; defaults to `false` and is checked at startup with a warning if `true`.)
