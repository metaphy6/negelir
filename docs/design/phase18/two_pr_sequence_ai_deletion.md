# Phase 18.3 & §22.4 — Two-PR Sequence for ai/ Deletion

**Ledger #4:** ai/ deletion is a two-PR sequence with a documented deprecation window.

**Reference:** ROADMAP.md §18.3 (gate design), §22.4 (execution).

---

## Why Two PRs?

A flag-day deletion (single PR) breaks:
- Every developer's open branch (merge conflict with `ai/` removal)
- Every in-flight Phase 17 patcher PR (path re-routing breaks)
- Every cached Docker layer that pinned the old path

Two PRs with a deprecation window:
1. **PR #1:** Delete `ai/`, land `xops/lint/ai_tree_resurrection.py` lint
2. **Window:** `cfg.ai_tree_removal_window_days` (default 14) where lint refuses re-adds
3. **PR #2:** Flip lint into permanent CI gate via `test_ai_tree_gone.py`

---

## PR #1 — Deletion + Resurrection Lint

**Title:** `[cross-component-move] Remove ai/ shim tree; land resurrection lint`

**CODEOWNERS:** Triple-approved (datasource, swarm, server).

**Changes:**
- Delete `ai/` directory entirely (except `.gitkeep` if desired for the empty dir)
- Add `xops/lint/ai_tree_resurrection.py` (this lint; checks ai/ is absent/shim-only)
- Update `Makefile` to add `make isolation.ai_tree_resurrection` target (temporary)
- Document the deprecation window in commit message

**Tests:**
- `test_ai_tree_gone.py` **EXPECTED TO FAIL** (green means ai/ is gone; red during window is OK)
- `test_ai_deletion_blocked_until_r2_shims_only.py` (verifies gate blocks premature deletion)

**CI Behavior:**
- `make isolation.shims-only` is green (prerequisite met ✓)
- `test_ai_tree_resurrection_blocked_by_lint.py` runs and passes (lint is in place)
- `test_ai_tree_gone.py` fails (expected; ai/ was just deleted)
- Window countdown starts: 14 days before PR #2

---

## Deprecation Window (14 days)

**Duration:** `cfg.ai_tree_removal_window_days` (default 14 days from PR #1 merge)

**Behavior:**
- Any PR that re-adds files to `ai/` is blocked by `xops/lint/ai_tree_resurrection.py`
- Developers who accidentally push ai/ resurrections get a clear error: "ai/ tree has been resurrected. Phase 22 §22.4 deletion is BLOCKED."
- If a resurrection is *intentional* (emergency rollback), it requires an emergency commit with `[RELAX_AI_TREE_RESURRECTION]` marker + dual CODEOWNERS ACK

**Monitoring:**
- `make resurrection.status` shows: "Window active; 10 days remaining"
- If window expires without issue, auto-proceed to PR #2

---

## PR #2 — Permanent Gate

**Issued:** After window expiration (day 15) with no resurrections.

**Title:** `[cross-component-move] ai/ deletion window expired; flip resurrection lint to permanent gate`

**Changes:**
- Rename/repurpose `xops/lint/ai_tree_resurrection.py` → permanent CI gate
- `test_ai_tree_gone.py` is now a permanent assertion (must pass in CI)
- Remove the temporary `make isolation.ai_tree_resurrection` target
- Update `Makefile` to add permanent `make isolation.ai_tree_gone` target

**Tests:**
- `test_ai_tree_gone.py` **EXPECTED TO PASS** (ai/ must stay gone forever)
- All existing isolation tests continue to run

**CI Behavior:**
- `test_ai_tree_gone.py` becomes a required CI gate
- Any PR that re-adds ai/ now fails `test_ai_tree_gone.py` permanently
- The lint is now part of standing isolation policy

---

## Emergency Rollback

**If ai/ must be resurrected during the window:**

1. Create emergency commit: `git revert <PR#1-commit-SHA>`
2. Add marker `[RELAX_AI_TREE_RESURRECTION]` to commit message
3. Require dual CODEOWNERS ACK (datasource + swarm)
4. CI recognizes marker and permits the resurrection
5. Emit alert: `sec.alert.v1{kind=ai_tree_resurrection_emergency_rollback}`
6. Restart window countdown (14 more days from rollback merge)

---

## Timeline Example

```
Day 0:   PR #1 merges → ai/ deleted, lint added, window starts
Day 1-13: Development continues; any ai/ re-add blocked by lint
Day 14:  Window countdown reaches zero
Day 15:  PR #2 merges → lint becomes permanent gate
Day 16+: ai/ deletion is permanent and enforced in CI
```

---

## Reference

- **ROADMAP:** `docs/planning/ROADMAP.md` §18.3 + §22.4
- **Ledger #4:** Retire wrong assumption "single-commit deletion"
- **Lint:** `xops/lint/ai_tree_resurrection.py`
- **Gate:** `test_ai_tree_gone.py`
