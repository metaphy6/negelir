# Phase 22.3 — Merge Conflict Resolution Playbook

**Status:** Phase 22.3.0 (Planning) — This document defines the canonical strategy and decision-tree for resolving four conflicting folders in the flat-layout migration.

**Applies to:** Every sub-phase of Phase 22.3 (§22.3a–§22.3d).

**Created:** 2026-06-21 — Binding reference for all merge operations.

---

## Overview of the Four Merge Targets

Phase 22.3 processes four folders that have both `ai/` and root-level versions. Each requires conflict-aware merging before any non-conflicting package moves (§22.4 onwards). The order matters — resolve in sequence:

1. **§22.3a: `ai/common/` → `common/`** — The largest and most complex merge
   - 5 overlapping sub-packages (`bus`, `config`, `db`, `isolation`, `observability`, `security`)
   - 2 top-level file collisions (`logger.py`, `international_tournament_profiles.py`)
   - 2 `ai`-only move-ins (`feeds/`, `api/`)
   - **Authoritative-copy is heterogeneous** (not "root wins")
   - **First to execute** — other merges depend on common being stable

2. **§22.3b: `ai/tests/` → `tests/`** — Reconcile test infrastructure
   - No root-level `tests/` exists today; this creates it
   - 6 conftests total (§22.3a touches 2, §22.3c touches 2, others untouched)
   - Must strip stale `sys.path` manipulation and `sys.modules` clearing
   - Deduplicate pytest markers

3. **§22.3c: `ai/swarm/` → `swarm/`** — Merge the swarm-AI implementation
   - Root `swarm/` has Phase 8 maintenance agents (CODEOWNERS-protected from patcher)
   - `ai/swarm/agents/` must merge without name collisions
   - Regenerate `requirements.lock` and `sbom.spdx.json` for new path
   - Two nested conftests move with their agents

4. **§22.3d: `ai/docs/` → `docs/ai_pipeline/`** — Absorb pipeline documentation
   - All markdown files move; cross-references updated
   - No root doc overwrites without CODEOWNERS review

---

## Heterogeneous Authority Principle (Binding)

**Key doctrine:** "Authoritative copy wins" does **not** mean the same source wins everywhere.

### Why heterogeneous authority?

- Some root packages are **shims** (re-exporting from `ai.*`) — the real implementation is in `ai/`, and must flip after the move.
- Some root packages are **real implementations** — `ai/` contributions are only additional symbols.
- Applying a uniform "root always wins" rule would delete real code or leave shims pointing at deleted trees.

### Ledger reference

See **Ledger Row #36** in `docs/planning/ROADMAP.md` §22.0:

> The authoritative copy for every overlapping `common/` sub-package is the Phase-18 root version.

**This row is wrong.** The correction is documented in §22.3a *decision table* below — `bus` and `config` are **`ai/`-authoritative shims**, and the direction flips.

---

## Decision-Tree Algorithm

**Apply this sequence for every overlapping file or sub-package:**

```
1. Identify the overlap:
   - Is there a file or sub-package at both <ai/path> and <root/path>?
   
2. Classify the root version:
   ✓ Real implementation: Keep as base, merge in `ai/`-unique symbols
   ✓ Shim (re-exports from ai.*): Delete and move real impl to root
   ✓ Stub (empty or placeholder): Replace with `ai/` version
   
3. If the root version is a REAL IMPLEMENTATION:
   - Diff both copies
   - Identify root-only files (keep untouched)
   - Identify colliding+differing files (symbol-union merge)
   - Identify `ai/`-only files (move into root)
   - Record every decision in the PLAYBOOK document
   - Gate on symbol-union preservation (no public API loss)
   
4. If the root version is a SHIM:
   - Move the `ai/` real implementation to root
   - Delete the shim (do NOT alias — an alias to a deleted tree is the bug)
   - Repoint every importer (codemod in same commit)
   
5. If the root version is a STUB or non-existent:
   - Move the `ai/` version verbatim
   
6. Emit a decision row into the PLAYBOOK document:
   Format: "| <overlap> | <action> | <reason> | <ledger-ref> |"
```

---

## Applying the Principle to §22.3a (`common/` merge)

**The merge table (canonical, binding for §22.3a):**

| Overlap | Root type | Action | Reason | Ledger |
|---|---|---|---|---|
| `common/bus/` | **Shim** re-exporting `ai.common.bus` | Move real impl to root; delete shim | Real code is in `ai/` | #36 |
| `common/config/__init__.py` | **Shim** with `sys.path.insert(0, ai_path)` | Move `ai/common/config.py` to `common/config/ai_pipeline.py`; repoint `__init__.py` to import from new path | Real config logic in `ai/` | #26, #36 |
| `common/db/` | **Real root impl** | Merge `ai/`-unique symbols only | Root base + AI additions | — |
| `common/isolation/` | **Real root impl** (carries Phase 18 gate) | Preserve 4 root-only files (`go_check.go`, snapshot, etc.); symbol-union merge 4 colliding+differing files onto root base | Root files are non-redundant; colliding files diverged (each contributes unique symbols) | #27 |
| `common/observability/` | **Real root impl** | Merge `ai/`-unique symbols only | Root base + AI additions | — |
| `common/security/` | **Real root impl** | Merge `ai/`-unique symbols only | Root base + AI additions | — |
| `common/logger.py` | Two **different** top-level files | Replace root with `ai/` version (richer); symbol-union check to ensure no root public symbol lost | `ai/` version is a superset; decision committed | #44 |
| `common/international_tournament_profiles.py` | Two **different** top-level files | Diff, decide authority, symbol-union merge | Requires explicit review; decision committed | #44 |
| `common/__init__.py` | Two **different** top-level files | Union of `__all__` from both copies | Decision committed | — |
| `common/feeds/` | **`ai`-only** (no root counterpart) | Pure move-in to `common/feeds/` | — | — |
| `common/api/` | **`ai`-only** (no root counterpart) | Pure move-in to `common/api/` | — | — |

---

## Symbol-Union Preservation Gate (Binding)

**Ledger Rows #43–#45** define three mechanical gates. All three must pass before a merge commit lands:

### Gate 1: File Accountability

**What:** Every source file is accounted for in exactly one destination action.

**How to verify:**
```bash
# Before move: generate manifest
make phase22.inventory > docs/tracking/phase22_move_plan.yaml

# After move: assert accountability
- Every ai/common/* → one action (move/merge/delete)
- No destination received two sources without a recorded merge decision
- No git mv used -f (force overwrites forbidden)
```

### Gate 2: Symbol-Union Preservation

**What:** The merged module's public surface ⊇ union of both source copies, minus an explicit allow-list.

**How to verify:**
```python
# For a merged module like common.db:
root_public_symbols = get_public_api(root_copy)
ai_public_symbols = get_public_api(ai_copy)
merged_public_symbols = get_public_api(merged_result)

expected = root_public_symbols | ai_public_symbols - dropped_symbols
assert expected ⊆ merged_public_symbols
```

**Dropped symbols require a proof entry** in `docs/decisions/phase22/dropped_symbols.md`:
```yaml
- symbol: old_function
  module: common.db
  reason: "No live callers; verified by vulture + grep"
  deprecation_window: "90 days from <date>"
```

### Gate 3: Content-Hash Preservation

**What:** Verbatim-moved files are byte-identical except authorised rewrites.

**How to verify:**
```bash
# Before move: record blob SHA for each file
python3 xops/codemod/record_file_hashes.py ai/common/ > docs/tracking/phase22_pre_merge_hashes.json

# After move: re-derive expected content and diff
python3 xops/codemod/verify_content_hash.py \
  --pre-hashes docs/tracking/phase22_pre_merge_hashes.json \
  --authorised-rewrites <list of patterns codemod was allowed to touch>
```

---

## Ledger References (Binding)

Every decision row in a sub-phase PLAYBOOK must cite at least one ledger row from §22.0 that justifies the decision:

**Relevant ledger rows for §22.3:**

| # | Title | Applies to |
|---|---|---|
| 2 | "`common/` and `ai/common/` overlap exactly five sub-packages" | All of §22.3a |
| 3 | Conftest hierarchy conflicts | §22.3b |
| 7 | `common/schemas/` requires CODEOWNERS ACK | §22.3a |
| 27 | `ai/common/isolation/` per-file diff-audit | §22.3a (isolation merge) |
| 28 | Non-`ai/` files must co-update with their target package | All sub-phases (codemod only) |
| 34 | `swarm/agents/` collision scan required | §22.3c |
| 36 | Authoritative copy is heterogeneous (`bus`, `config`, `db`, etc.) | §22.3a |
| 37 | Per-component lockfiles/SBOMs regenerated | §22.3a, §22.3c |
| 41 | Six conftests to reconcile | §22.3b |
| 42 | Betting markets and entitlements deduplicated | §22.3a |
| 43 | File-accountability manifest | All sub-phases |
| 44 | Symbol-union preservation gate | All sub-phases |
| 45 | Content-hash preservation gate | All sub-phases |

---

## Testing the Playbook

**Proof tests (per ROADMAP §22.3 DoD):**

Each sub-phase ships ≥6 proof tests. Example for §22.3a:

- `test_22_3a_common_merge_no_duplicate_symbols.py` — no symbol defined twice
- `test_22_3a_merge_preserves_symbol_union.py` — symbol-union gate passes
- `test_22_3a_file_accountability_complete.py` — every source file accounted for
- `test_22_3a_common_schemas_subpackage_charter.py` — schema module has charter entry
- `test_22_3a_bus_shim_flipped_no_reexport_from_ai.py` — shim deleted, not aliased
- `test_22_3a_no_common_module_reexports_from_ai_tree.py` — no shim orphans

**See `docs/decisions/phase22/common_merge_decisions.md`** for the full sub-phase-specific proof checklist.

---

## Rollback Strategy

**If a merge fails:**

1. Identify the failing sub-phase (22.3a, 22.3b, 22.3c, or 22.3d).
2. Run `make phase22.rollback STEP=<N>` where N is the sub-phase number.
3. This command:
   - Reverses all commits from that sub-phase in reverse order
   - Re-runs `make isolation.check --full` to confirm no gate regressions
   - Re-runs `PYTHONPATH=. make test` to confirm test suite green
   - Re-validates no `ai/` or `datasource/` shims are orphaned
   - Refreshes the isolation snapshot

**Two consecutive rollbacks of the same sub-phase without a fix → pause and escalate.**

---

## Checkpoints & Bookkeeping

Per **AGENTS.md §3.4** and **§6.1:**

- [ ] Every sub-phase ships its own **tracker row** (`make track.add PHASE=22 SUBPHASE=<N> STATUS=...`).
- [ ] Every sub-phase ships its own **version bump** (`make version.bump COMPONENT=xops LEVEL=...`).
- [ ] Every sub-phase's ROADMAP checkboxes flipped to `[x]` in the same commit.
- [ ] Per sub-phase PLAYBOOK document (`common_merge_decisions.md`, `tests_merge_decisions.md`, etc.) committed before any files move.

**Phase 22.3.0 milestone (this document):**
- `docs/decisions/phase22/22_3_merge_strategy.md` ← **this file**
- `docs/decisions/phase22/common_merge_decisions.md` ← sub-phase 22.3a binding decisions
- `ai/tests/test_22_3_merge_conflict_resolution_is_documented.py` ← proof test

---

## Next: Read `docs/decisions/phase22/common_merge_decisions.md`

Once this playbook is committed, the 22.3a-specific decision document provides the per-file resolution for the `common/` merge, including a symbol-union audit checklist and deprecation-calendar entries.

