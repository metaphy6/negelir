# Phase 9.11 — Versioning, deprecation, sunset policy

> Extracted from `docs/planning/ROADMAP.md` §9.11
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.11 Versioning, deprecation, sunset policy

- [x] **`/v1` is the public contract.** Breaking changes cut `/v2` — never break `/v1` in place.
- [x] **Deprecation window** = 90 days minimum (`cfg.api_deprecation_window_days`). Deprecated routes return `Sunset: <RFC 8594 date>` + `Link: </v2/...>; rel="successor-version"` headers; OpenAPI marks them with `x-deprecated-on` / `x-sunset-on`. Past the sunset date → `410 gone` with `Link` to the successor.
- [x] **Field-level deprecation.** Deprecated response field carries a sibling `<field>_deprecated: true` for one minor version then is removed in the next minor. OpenAPI validator gates.
- [x] **Schema-version stamping.** Every JSON response carries `meta.schema_version` (tracks `cfg.api_schema_version`, bumps additively per `chart.json` `server` minor). Client SDKs key cache invalidation on this.
