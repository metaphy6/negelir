# Phase 13.27 — Backwards-compat & deprecation policy

> Extracted from `docs/planning/ROADMAP.md` §13.27
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.27 Backwards-compat & deprecation policy

> Retires assumption §13.0 #28.

- [ ] **Per-field metadata.** Each `LeagueRow` / `LeagueConfig` field carries `added_in: <chart_version>`, `deprecated_in: <chart_version>?`, `removed_in: <chart_version>?` in the JSONSchema; `xops/lint/league_field_lifecycle.py` enforces.
- [ ] **Sunset window.** A field marked `deprecated_in=X.Y.Z` cannot be removed before `X.Y+2.Z` (≥ 2 minor versions); lint refuses earlier removal.
- [ ] **Migration helpers.** `xops/leagues/migrations/<from>__to__<to>.py` carries `up()` and `down()` functions; CI runs `up → down → up` round-trip on a synthetic catalog.
- [ ] **Client deprecation header.** Phase 9 API surfaces deprecation via `Sunset` HTTP header (RFC 8594) + `Deprecation` header per IETF draft; OpenAPI schema-validation gate ensures old clients still parse responses.
- [ ] **Shadow-period for breaking changes.** Any field marked `removed_in` triggers a Phase 11 §11.26 shadow inference window where the old + new semantics run in parallel for `cfg.field_removal_shadow_days` (default 30) before the old code path is deleted.
