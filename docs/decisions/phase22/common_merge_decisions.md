# Phase 22.3a — `common/` Merge: Specific Decisions & Resolution

**Status:** Phase 22.3a (Pre-move planning) — This document binds the authoritative-copy decisions and per-file conflict resolutions for merging `ai/common/` → `common/`.

**Created:** 2026-06-21 — Must be committed before any files move.

**Binding reference:** `docs/decisions/phase22/22_3_merge_strategy.md` (the general playbook and decision-tree algorithm).

---

## Per-Sub-Package Authority & Merge Action (Canonical)

**Read this table in sequence; apply every decision exactly as written.**

| Sub-package | Root type | Authoritative copy | Merge action | Ledger | Notes |
|---|---|---|---|---|---|
| `common/bus/` | **Shim** re-exporting `ai.common.bus` | **`ai/common/bus/`** | Move real impl to `common/bus/`; **delete shim** (no alias); repoint all importers | #36 | Root `__init__.py` and `publisher.py` re-export from `ai.common.bus`; the real code lives in `ai/`. After merge, `common/bus/` contains the implementation, `ai/common/bus/` is deleted, and all references are rewritten by codemod. |
| `common/config/` | **Shim** with `sys.path.insert` trick | **`ai/common/config.py`** | Move `ai/common/config.py` → `common/config/ai_pipeline.py`; rewrite `common/config/__init__.py` to `from common.config.ai_pipeline import Config, cfg` (remove `sys.path.insert`); delete shim machinery | #26, #36 | Root `__init__.py` uses `sys.path.insert(0, _ai_path)` to import from `ai.common.config`. After move, the real config lives at `common/config/ai_pipeline.py`, and the init file imports from there directly. |
| `common/db/` | **Real root impl** — Phase 18 governed | **Root (base) + merge `ai/`-unique symbols** | No overwrite; extract `ai/`-unique public symbols; symbol-union merge onto root version | #44 | Root `common/db/` is a real implementation with production code. `ai/common/db/` contains AI-specific additions. Both `public_api` methods are merged. |
| `common/isolation/` | **Real root impl** — carries Phase 18 gate (`go_check.go`, snapshot, graph_builder.py, forbidden_deps.yaml) | **Root (base) + per-file diff-audit for 4 colliding files** | Preserve **all 4 root-only files untouched**; for the 4 colliding+differing files, symbol-union merge onto root base | #27, #44 | `go_check.go` is a Go-embedded security gate and MUST NOT be touched. The 4 Python files that differ both have unique public symbols; both need to be preserved. See sub-section below. |
| `common/observability/` | **Real root impl** — Phase 18 governed | **Root (base) + merge `ai/`-unique symbols** | For each colliding file (`metrics.py`, `alerts.py`, `__init__.py`): symbol-union merge onto root version | #44 | `ai/common/observability/` contributes NLP-specific metrics. Both versions have public APIs; union is required. |
| `common/security/` | **Real root impl** — Phase 18 governed | **Root (base) + merge `ai/`-unique symbols** | For colliding file (`input_sanitiser.py`): symbol-union merge onto root version | #44 | `ai/common/security/` has NLP input-specific sanitization rules. Both versions' public symbols must be preserved. |

---

## Per-File Conflict Resolution (7 files)

### File 1: `common/__init__.py` vs `ai/common/__init__.py`

**Status:** Two different `__all__` and exports.

**Decision:** Union both `__all__` declarations.

**Action:**
```python
# Pre-merge: capture both __all__
root_all = <symbols in common/__init__.py::__all__>
ai_all = <symbols in ai/common/__init__.py::__all__>

# Post-merge: union
merged_all = sorted(set(root_all) | set(ai_all))
```

**Proof:** `test_22_3a_top_level_init_union_resolved.py` asserts `merged __all__ == union of both sources`.

**Ledger:** #44 (symbol-union preservation).

---

### File 2: `common/logger.py` vs `ai/common/logger.py`

**Status:** Two different implementations. `ai/common/logger.py` is larger and more feature-rich.

**Decision:** Use `ai/common/logger.py` as the authoritative version; verify no public symbol of the root version is lost.

**Action:**
1. Capture root `common/logger.py` public symbols (via `grep -E "^(def|class) [A-Z]"`).
2. Capture `ai/common/logger.py` public symbols.
3. Confirm union: assert `ai_symbols ⊇ root_symbols`.
4. Move `ai/common/logger.py` → `common/logger.py` (overwriting root version).

**Proof:** `test_22_3a_logger_conflict_resolved_single_authoritative.py` checks that no public symbol from the root copy was lost.

**Ledger:** #44.

---

### File 3: `common/international_tournament_profiles.py` vs `ai/common/international_tournament_profiles.py`

**Status:** Two different implementations. Per ROADMAP Ledger #42 audit (2026-06-20), both exist and differ.

**Decision:** Diff audit required; placeholder: **TBD** (awaiting manual review).

**Action (placeholder for human review):**
1. Generate side-by-side diff: `diff common/international_tournament_profiles.py ai/common/international_tournament_profiles.py`
2. Identify which version is authoritative or if both must be merged.
3. Record decision in this document under "Decision outcome (post-review)".
4. If merging: symbol-union merge (see §22.3a Proof Tests below).

**Decision outcome (post-review):** 

```
[PLACEHOLDER: Human review required before first commit. Document outcome here.]
```

**Proof:** `test_22_3a_intl_tournament_profiles_conflict_resolved.py` verifies the chosen resolution.

**Ledger:** #44.

---

### File 4: `common/isolation/check.py` vs `ai/common/isolation/check.py`

**Status:** Two different implementations; both have public APIs.

**Decision:** Symbol-union merge onto root base (root is authoritative, AI symbols folded in).

**Action:**
1. Capture root `common/isolation/check.py` public symbols.
2. Capture `ai/common/isolation/check.py` public symbols.
3. Merge: keep root implementation as base; append `ai/`-unique functions/classes/constants to the end (with a marker comment `# === AI-specific symbols ===`).
4. Ensure no name collisions; if collision exists, rename `ai/` symbol with suffix (e.g. `_ai_variant`) and document the rename.

**Proof:** `test_22_3a_dpa_validator_symbol_union_merged.py` verifies union; `test_22_3a_isolation_colliding_files_symbol_union_merged.py` confirms for all colliding files.

**Ledger:** #27 (isolation per-file merge), #44 (symbol-union).

---

### File 5: `common/isolation/policy.py` vs `ai/common/isolation/policy.py`

**Status:** Two different implementations; both have public APIs.

**Decision:** Symbol-union merge onto root base (same protocol as File 4).

**Action:** Apply identical protocol to File 4.

**Proof:** Covered by `test_22_3a_isolation_colliding_files_symbol_union_merged.py`.

**Ledger:** #27, #44.

---

### File 6: `common/isolation/dpa_validator.py` vs `ai/common/isolation/dpa_validator.py`

**Status:** Two different implementations; both have public APIs. Per Ledger #27, this file exists in both trees and differs.

**Decision:** Symbol-union merge onto root base (same protocol).

**Action:** Apply identical protocol to File 4.

**Proof:** Covered by `test_22_3a_isolation_colliding_files_symbol_union_merged.py` and specifically named `test_22_3a_dpa_validator_symbol_union_merged.py`.

**Ledger:** #27 (this was the "only net-new file" assumption — verified wrong by audit), #44.

---

### File 7: `common/isolation/__init__.py` vs `ai/common/isolation/__init__.py`

**Status:** Two different `__all__` lists.

**Decision:** Union both `__all__` declarations (same as File 1).

**Action:**
```python
root_all = <symbols in common/isolation/__init__.py::__all__>
ai_all = <symbols in ai/common/isolation/__init__.py::__all__>
merged_all = sorted(set(root_all) | set(ai_all))
```

**Proof:** `test_22_3a_isolation_union_resolved.py` asserts union.

**Ledger:** #44.

---

## Root-Only Isolation Files (Preserved Untouched)

The following four files exist **only in root** `common/isolation/` and carry the Phase 18 security gate. They are **NOT** touched:

| File | Reason | Size (as of audit) |
|---|---|---|
| `common/isolation/go_check.go` | Go-embedded security gate (cross-language DPA check) | ~1 500 lines |
| `common/isolation/graph_builder.py` | Builds the import-dependency graph (Phase 18 gate) | ~500 lines |
| `common/isolation/forbidden_deps.yaml` | Isolation policy rules (DPA + zone separation) | ~200 lines |
| `common/isolation/import_graph.snapshot.json` | Phase 18 pre-computed baseline (gate reference) | ~50 KB |

**Proof:** `test_22_3a_isolation_root_only_files_preserved.py` verifies all four exist and are byte-identical post-merge.

**Ledger:** #27 (isolation is a root-only gate carrier).

---

## AI-Only Move-Ins (No Merge Required)

The following sub-packages exist **only under `ai/common/`** and move verbatim:

- `ai/common/feeds/` → `common/feeds/` (feed schema definitions + generated models)
- `ai/common/api/` → `common/api/` (OpenAPI + wire contract definitions)

**No root counterpart exists.** These are pure move-ins.

**Proof:** `test_22_3a_feeds_and_api_are_pure_move_ins.py` confirms no collisions.

**Ledger:** #2 (verified inventory).

---

## Other `ai/common/` Files Requiring Repointing or Special Handling

### `ai/common/config.py` → `common/config/ai_pipeline.py`

**Issue:** Root `common/config/__init__.py` has a `sys.path.insert(0, _ai_path)` trick to import from `ai.common.config`.

**Action:**
1. Move `ai/common/config.py` → `common/config/ai_pipeline.py`.
2. Rewrite `common/config/__init__.py`:
   ```python
   # Before
   import sys
   _ai_path = ...
   sys.path.insert(0, _ai_path)
   from ai.common.config import Config, cfg
   sys.path.pop(0)
   
   # After
   from common.config.ai_pipeline import Config, cfg
   __all__ = ["Config", "cfg"]
   ```
3. Delete root `common/config/__init__.py` `sys.path` hack.

**Proof:** `test_22_3a_config_init_no_longer_imports_ai.py` verifies the shim is flipped.

**Ledger:** #26 (canonical config location), #36 (shim direction).

---

### `ai/common/betting_markets.json` → `data/betting_markets.json`

**Issue:** This is a data-contract file read via a config key. Moving it requires updating the config reference atomically.

**Action:**
1. Move `ai/common/betting_markets.json` → `data/betting_markets.json`.
2. Update `common/config/defaults.yaml` or the runtime config:
   ```yaml
   betting_markets_path: "data/betting_markets.json"
   ```
3. Verify every reference to the old path is removed.

**Proof:** `test_22_3a_betting_markets_config_key_updated.py` verifies the path is config-driven.

**Ledger:** #42 (data-contract move).

---

### `ai/common/entitlements.yaml` → Deduplicate against `xops/monetization/entitlements.yaml`

**Issue:** Per Ledger #42, entitlements exist in **two places**:
- `ai/common/entitlements.yaml` (AI-pipeline copy)
- `xops/monetization/entitlements.yaml` (Phase 20 canonical)

**Action:**
1. Diff both files to identify divergence.
2. **Do NOT create a forked second copy.** Either:
   - **Option A:** Phase 20 canonical is authoritative; `ai/common/entitlements.yaml` is deleted and documented as "reconciled into Phase 20 canonical".
   - **Option B:** AI pipeline has critical additions; record them in Phase 20 canonical, then delete the `ai/` copy.
3. Record which option was chosen and why in this document.

**Decision:** 

```
[PLACEHOLDER: Requires Phase 20 CODEOWNERS review before first commit.]
```

**Proof:** `test_22_3a_entitlements_deduplicated.py` verifies no forked copies remain.

**Ledger:** #42 (de-duplication required).

---

## Deprecation Calendar Entries (Post-Merge)

After the merge, the following deprecations are scheduled (written to `xops/lifecycle/deprecation_calendar.yaml`):

**Note:** Shim deletions (§22.3a) do NOT get a 90-day alias window. Shims are deleted because they point at a tree being removed. Any surviving importer MUST be co-updated by the codemod in the same commit.

**Conditional entries (only if true live callers remain that cannot be co-updated):**

```yaml
# If any live caller outside the merger's scope still imports from ai.common.bus after merge:
- component: common.bus
  old_path: ai.common.bus
  new_path: common.bus
  deprecation_window: "90 days from <merge-commit-date>"
  reason: "Shim re-export during transition; all callers must migrate by deadline"
  eol_action: "emit DeprecationWarning, then error"

# If any live caller outside the merger's scope still imports from ai.common.config after merge:
- component: common.config
  old_path: ai.common.config
  new_path: common.config.ai_pipeline
  deprecation_window: "90 days from <merge-commit-date>"
  reason: "Shim re-export during transition; all callers must migrate by deadline"
  eol_action: "emit DeprecationWarning, then error"
```

**Note:** The codemod co-updates all non-`ai/` callers (44 in `xops/`, 10 in `common/`, 1 in `docs/`) in the same commit. If co-update succeeds 100%, no deprecation window is needed.

---

## Symbol-Union Audit Checklist (Before First Commit)

**Run these verification steps before merging any `ai/common/` file:**

- [ ] For each root-authoritative overlap (`db`, `isolation`, `observability`, `security`):
  - [ ] `root_symbols = extract_public_api(common/<subpkg>/)`
  - [ ] `ai_symbols = extract_public_api(ai/common/<subpkg>/)`
  - [ ] `merged = merge_symbol_union(root_base, ai_symbols)`
  - [ ] Assert `merged_symbols ⊇ (root_symbols | ai_symbols)`
  - [ ] If any symbol dropped (outside allow-list), investigate and document reason

- [ ] For each `ai/`-authoritative shim (`bus`, `config`):
  - [ ] Verify root version re-exports from `ai.*` (confirm it is a shim, not a divergent implementation)
  - [ ] Verify real implementation is in `ai/`
  - [ ] After move, confirm `common/` version is not a shim (no `from ai.*`)

- [ ] For top-level file collisions (`logger.py`, `international_tournament_profiles.py`, `__init__.py`):
  - [ ] Diff both versions
  - [ ] Decide authority (or union if both needed)
  - [ ] Apply symbol-union merge if union is chosen
  - [ ] Record decision here

- [ ] For the four `common/isolation/` colliding files (`check.py`, `policy.py`, `dpa_validator.py`, `__init__.py`):
  - [ ] Confirm root-only files (`go_check.go`, snapshot, etc.) are preserved untouched
  - [ ] Symbol-union merge each colliding file
  - [ ] Verify no Phase 18 gate regression

- [ ] For root-only move-ins (`feeds/`, `api/`):
  - [ ] Confirm no root counterpart exists
  - [ ] Verify no naming collision with existing `common/` modules
  - [ ] Move verbatim (codemod updates internal `ai.common.*` imports to `common.*`)

- [ ] For data-contract moves:
  - [ ] Betting markets: config key updated, old path gone
  - [ ] Entitlements: deduplicated, no forked copy remains

---

## Proof Tests (Commit in Same PR as Merge)

Each proof test validates one aspect of the merge. **All must pass before merge is complete.**

| Test name | What it verifies | Ledger |
|---|---|---|
| `test_22_3a_common_merge_no_duplicate_symbols` | No symbol defined twice in merged modules | #44 |
| `test_22_3a_merge_preserves_symbol_union` | Symbol-union gate green for all overlaps | #43–#45 |
| `test_22_3a_file_accountability_complete` | Every `ai/common/` source mapped to one destination | #43 |
| `test_22_3a_no_forced_git_mv` | No `git mv -f` was used (no clobber) | #43 |
| `test_22_3a_isolation_root_only_files_preserved` | Four root-only gate files byte-identical | #27 |
| `test_22_3a_intl_tournament_profiles_conflict_resolved` | Conflict resolution decision executed | #44 |
| `test_22_3a_top_level_init_union_resolved` | `__init__.py` `__all__` is union of both | #44 |
| `test_22_3a_common_schemas_subpackage_charter` | `common.schemas` has charter entry + CODEOWNERS ACK | #7 |
| `test_22_3a_ai_common_nlp_becomes_nlp_vocab` | `ai/common/nlp/` renamed to `common/nlp_vocab/` (prevents collision with root `nlp/`) | #2 |
| `test_22_3a_logger_conflict_resolved_single_authoritative` | Logger conflict resolved; no public symbol lost | #44 |
| `test_22_3a_config_init_no_longer_imports_ai` | Shim flipped; `common/config/__init__.py` imports from `ai_pipeline`, not `ai.*` | #26, #36 |
| `test_22_3a_bus_shim_flipped_no_reexport_from_ai` | Bus shim deleted; no `common/bus/` file re-exports from `ai.*` | #36 |
| `test_22_3a_no_common_module_reexports_from_ai_tree` | No orphaned shims left pointing at `ai/` (which will be deleted) | #36 |
| `test_22_3a_go_check_survives_merge` | Go gate file `common/isolation/go_check.go` byte-identical | #27 |
| `test_22_3a_dpa_validator_symbol_union_merged` | DPA validator symbols from both trees preserved | #27, #44 |
| `test_22_3a_feeds_and_api_are_pure_move_ins` | `common/feeds/` and `common/api/` have no root collision | #2 |
| `test_22_3a_betting_markets_config_key_updated` | Betting markets path is config-driven, not hardcoded | #42 |
| `test_22_3a_entitlements_deduplicated` | No forked entitlements copy; merged against Phase 20 canonical | #42 |

---

## Rollback Instructions (If merge fails)

```bash
# Reverse the merge commit
git revert <merge-commit-sha>

# Re-validate Phase 18 gates
make isolation.check --full

# Re-run tests
PYTHONPATH=. make test

# Re-confirm no orphaned shims
make isolation.shims-only  # should still fail (ai/ still present)

# Refresh snapshot
make isolation.snapshot.refresh
```

**If rollback succeeds twice without a fix, pause and escalate.**

---

## Bookkeeping (Same Commit as Merge)

- [ ] Merge commit lands with all proof tests passing
- [ ] `make track.add PHASE=22 SUBPHASE=3 STATUS=in-progress NOTE="22.3a merge: ai/common/ → common/ conflict resolution in progress"`
- [ ] `make track.add PHASE=22 SUBPHASE=3 STATUS=completed NOTE="22.3a complete: all 5 sub-pkg overlaps merged, 7 file conflicts resolved, symbol-union gates green, no orphaned shims"`
- [ ] ROADMAP checkboxes flipped to `[x]` for §22.3a
- [ ] `make version.bump COMPONENT=xops LEVEL=patch NOTE="Phase 22.3a: ai/common/ → common/ merge complete, heterogeneous authority applied, symbol-union gates green"`

