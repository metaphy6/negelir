# Component Versioning & Public-API Deprecation Policy

> **Phase:** 18.5 (R4) — Versioning finalization (ledger #7)
> **Anchor:** [`AGENTS.md` §6.1](../../AGENTS.md) + [`ROADMAP.md` §18.5](../planning/ROADMAP.md)
> **Status:** Binding policy for all 1.0.0+ components.

---

## 1. Overview

This document defines the public-API deprecation policy and versioning discipline for Negelir components reaching stable (≥ 1.0.0) status.

**Scope:** Every component with version ≥ 1.0.0 must observe these rules.

**Non-scope:** Phase-internal scaffolding (0.x.x versions) is free to change without deprecation windows.

---

## 2. Version Lifecycle & Stability Guarantees

### 2.1 Pre-stable (0.x.x)

- **Public surface:** unrestricted churn allowed. No backwards-compatibility window.
- **Changelog:** changes still recorded in chart.json for audit; no deprecation notes required.
- **Use case:** Phase-internal components, experimental APIs, scaffolding.

### 2.2 Stable (1.0.0+)

- **Public surface:** frozen. Breaking changes require major version bump.
- **API migration window:** ≥ 1 minor version (≥ ~4 weeks on a monthly release cycle).
- **User notification:** deprecation warnings in logs + docs + release notes for ≥ 1 minor before removal.
- **Removal:** only after the window closes on a major-version boundary.

---

## 3. Deprecation Process (Stable Components)

### 3.1 Removal Candidate Criteria

A public-API surface becomes a removal candidate when it:

- (a) Has been superseded by a newer interface, OR
- (b) Has become obsolete (no production use case), OR
- (c) Creates a persistent maintenance burden with diminishing returns.

**Decision point:** Team consensus + `docs/decisions/` ADR.

### 3.2 Deprecation Announcement (Minor Bump)

1. **Mark as deprecated:**
   - Annotate the symbol with `@deprecated(removal_version="X.Y.0", replacement="new_symbol()")`.
   - Update docstring with removal timeline.

2. **Emit runtime warning:**
   - Call sites log a structured deprecation warning (level=`warn`, category=`deprecation`, component name, removal ETA).
   - Warning includes the replacement or migration path.

3. **Update changelog:**
   - Record the bump as `minor` with note: `"deprecated: <symbol> — scheduled for removal in X.Y.0 (replacement: <new_symbol>)"`.

4. **Documentation:**
   - Migration guide under `docs/guides/migration/X.Y/deprecations.md`.
   - Pinned to the release notes.

### 3.3 Removal (Major Bump)

1. **Delete the deprecated symbol.**
2. **Update all consuming code paths** (component + all documented examples).
3. **Update changelog:** note references the prior deprecation announcement.

---

## 4. Public-API Freeze Gate (Phase 18 Mandatory)

To release a component at version 1.0.0, the following three artifacts **must exist**:

| Artifact | Purpose | Location | Notes |
|---|---|---|---|
| `<component>/PUBLIC_API.md` | Frozen surface contract | Component root | CODEOWNERS-protected; regenerated from `__all__` via `make docs.api` (Bullet 3) |
| `<component>/tests/test_public_api_compat.py` | Compatibility test suite | Component tests | Pins exports, signatures, and return-type shapes; runs on every CI and pre-release |
| `docs/coding/component_versioning.md` | This policy | Docs | Single source of truth for deprecation discipline across all 1.0.0+ components |

Absence of any one blocks the bump to 1.0.0 — `xops/versioning/version.py bump --to-1.0.0 --component <key>` refuses.

---

## 5. SemVer Mapping

| Change Type | Bump | Window | Removal |
|---|---|---|---|
| New public symbol | **minor** | not applicable | not applicable |
| Deprecate public symbol | **minor** | ≥ 1 minor version | major bump only |
| Change symbol signature | **major** | immediate (breaking) | immediate |
| Performance improvement (no API change) | **patch** | not applicable | not applicable |
| Bug fix (no API change) | **patch** | not applicable | not applicable |

---

## 6. Components Reaching 1.0.0 in Phase 22

The eight components listed in `xops/versioning/chart.json` with `will_reach_1_0_0_in_phase: 22` are:

1. `datasource_scraper` (Pivot v3)
2. `datasource_watcher` (Pivot v3 rename of source_watcher)
3. `datasource_refresher` (Pivot v3)
4. `datasource_patcher` (Pivot v3)
5. `datasource_gitops` (Pivot v3)
6. `swarm` (Pivot v3)
7. `common` (Pivot v3)
8. (Two already frozen in Phase 16: `datasource_emitter`, `common_feeds`)

Each must have all three freeze-gate artifacts before Phase 22 can execute their 1.0.0 bumps.

---

## 7. Key Policies

- **No silent breaking changes.** A breaking change without a deprecation window is a production incident.
- **No pre-emptive removal.** A symbol can only be removed if it has had ≥ 1 minor-version deprecation window.
- **Single deprecation per symbol.** Once deprecated, a symbol cannot be "un-deprecated." Instead, use a new name and deprecate the old one.
- **Cross-component symbols** (exported from `common.*`) follow the same policy; consumer updates are coordinated via ADR.

---

## 8. References

- [`ROADMAP.md` §18.5](../planning/ROADMAP.md) — Phase 18 versioning gates.
- [`ROADMAP.md` §22](../planning/ROADMAP.md) — Phase 22 execution of 1.0.0 bumps.
- [`xops/versioning/chart.json`](../../xops/versioning/chart.json) — component registry.
- [`xops/versioning/version.py`](../../xops/versioning/version.py) — CLI gate implementation.
