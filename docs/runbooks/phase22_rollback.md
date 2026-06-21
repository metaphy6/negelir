# Phase 22 Flat-Layout Migration Rollback Runbook

**Phase:** 22 — Flat-layout migration  
**Author:** Phase 22 implementation  
**Date:** 2026-06-21  
**Status:** Active (for structured rollback only)  
**Last updated:** 2026-06-21

## Overview

This runbook describes the 14-step rollback procedure for Phase 22 (flat-layout
migration). It is intended for use when a migration commit must be reverted due
to a test failure, isolation breakage, or unrecoverable error.

**Key principles:**
- Rollbacks are **per-step**, not per-commit. Each step may span multiple commits.
- Each rollback reverses commits in **reverse order** of creation.
- After every rollback, isolation checks and unit tests are re-run.
- Two consecutive failed rollback attempts in the same step trigger migration pause.
- `git revert` frequently produces conflicts on dense refactor commits — prefer
  explicit per-file reverts when conflicts arise.

## Architecture of the 14 Migration Steps

| Step | Sub-phase | Content | Typical commits | Rollback command |
|---|---|---|---|---|
| 1 | 22.1 | Pre-flight inventory & gates | 1–5 | `make phase22.rollback STEP=1` |
| 2 | 22.2 | Codemod engine | 2–4 | `make phase22.rollback STEP=2` |
| 3a | 22.3a | `common/` merge | 1–3 | `make phase22.rollback STEP=3a` |
| 3b | 22.3b | `ai/tests/` merge | 1 | `make phase22.rollback STEP=3b` |
| 3c | 22.3c | `ai/swarm/` merge | 1–2 | `make phase22.rollback STEP=3c` |
| 3d | 22.3d | `ai/docs/` merge | 1 | `make phase22.rollback STEP=3d` |
| 4 | 22.4 | Package moves (11 moves) | 11 | `make phase22.rollback STEP=4[a-k]` |
| 5 | 22.5 | Go references | 1–2 | `make phase22.rollback STEP=5` |
| 6 | 22.6 | Config migration | 1–2 | `make phase22.rollback STEP=6` |
| 7 | 22.7 | Deletion & shim cleanup | 1–2 | `make phase22.rollback STEP=7` |
| 8 | 22.8 | Snapshot finalization | 1 | `make phase22.rollback STEP=8` |
| 9 | 22.9 | Metric names | 1 | `make phase22.rollback STEP=9` |
| 10 | 22.10 | Version bumps | 1 | `make phase22.rollback STEP=10` |
| 11 | 22.12 | Patcher artefacts | 1 | `make phase22.rollback STEP=11` |
| 12 | 22.13 | Burn-in + monitoring | — | (read-only phase) |

---

## Step 1: Pre-flight Inventory & Gates (Phase 22.1)

**Commits to revert:** All Phase 22.1 pre-flight infrastructure (inventory scripts,
audit scripts, proof tests, runbook).

**Rollback command:**

```bash
make phase22.rollback STEP=1
```

**Manual rollback (if `make` target fails):**

```bash
cd /home/tech/code/negelir
# Revert Phase 22.1 commits in reverse order
git log --oneline --grep="Phase 22.1" | head -5 | awk '{print $1}' | sort -r | while read commit; do
  git revert --no-edit "$commit"
done

# Remove generated artefacts
rm -f docs/tracking/phase22_*.json
rm -f docs/tracking/phase22_*.txt
rm -f docs/tracking/phase22_*.yaml
rm -f ai/tests/test_22_1_*.py

# Restore the pre-flight state
PYTHONPATH=. make test
PYTHONPATH=. make isolation.check --full
```

**Verification:**

```bash
# Confirm ai/ is back to its original state
ls -la ai/ | grep -E "^d" | wc -l  # Should match baseline

# Confirm no Phase 22 output artefacts remain
ls -la docs/tracking/ | grep -i phase22  # Should be empty

# Confirm isolation gates are green
make isolation.check --full
```

---

## Step 2: Codemod Engine (Phase 22.2)

**Commits to revert:** Implementation of `xops/codemod/phase22_rewriter.py`,
codemod tests, and dispatcher.

**Rollback command:**

```bash
make phase22.rollback STEP=2
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
# Revert in reverse chronological order
git log --oneline --grep="Phase 22.2\|codemod engine" | head -10 | awk '{print $1}' | sort -r | while read commit; do
  git revert --no-edit "$commit"
done

# Remove codemod module
rm -rf xops/codemod/

# Confirm no imports are broken
PYTHONPATH=. make test
```

**Verification:**

```bash
# Confirm xops/codemod/ is removed
test ! -d xops/codemod/ && echo "OK: xops/codemod removed"

# Confirm import reports are green
PYTHONPATH=. make isolation.check --full
```

---

## Step 3a: common/ Merge (Phase 22.3a)

**Commits to revert:** Merge of `ai/common/` into `common/`, including:
- `common/bus/`, `common/db/`, `common/isolation/`, `common/observability/`, `common/security/`
- `common/feeds/`, `common/api/`, `common/schemas/`
- `ai/common/config.py` → `common/config/ai_pipeline.py`

**Rollback command:**

```bash
make phase22.rollback STEP=3a
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
# List commits for this step (typically 1–3)
git log --oneline --all --grep="22.3a\|common.*merge" | head -10

# Revert in reverse order
git revert --no-edit <latest-commit-hash>
git revert --no-edit <previous-commit-hash>
# ... repeat for all commits in the step

# Re-run tests against transitional layout
PYTHONPATH=ai make test
```

**Verification:**

```bash
# Confirm ai/common/ is restored
test -d ai/common/ && echo "OK: ai/common/ restored"

# Confirm root common/* are back to shim-only
find common/ -type f -name "*.py" | xargs grep -l "from ai\." | wc -l  # Should match baseline

# Confirm isolation is green
make isolation.check --full
```

---

## Step 3b: ai/tests/ Merge (Phase 22.3b)

**Commits to revert:** Merge of `ai/tests/` into root `tests/`.

**Rollback command:**

```bash
make phase22.rollback STEP=3b
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
# Revert the single or paired commits for this step
git log --oneline --all --grep="22.3b\|ai/tests" | head -5
git revert --no-edit <commit-hash>

# Restore ai/tests/
git checkout HEAD~1 -- ai/tests/conftest.py

# Re-run test discovery
PYTHONPATH=ai python3 -m pytest --collect-only tests/ ai/tests/ 2>&1 | head -20
```

**Verification:**

```bash
# Confirm ai/tests/ is restored
test -d ai/tests/ && echo "OK: ai/tests/ restored"

# Confirm root tests/ is back to original state
ls tests/ | wc -l  # Baseline count

# Confirm conftest hierarchy is correct
python3 conftest.py  # Should parse without error
```

---

## Step 3c: ai/swarm/ Merge (Phase 22.3c)

**Commits to revert:** Merge of `ai/swarm/` into root `swarm/`, including agent
name collision resolution and nested conftest reconciliation.

**Rollback command:**

```bash
make phase22.rollback STEP=3c
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.3c\|swarm.*merge" | head -5 | awk '{print $1}' | sort -r | while read commit; do
  git revert --no-edit "$commit"
done

# Verify swarm/ structure
ls -la swarm/ | grep "^d"
```

---

## Step 3d: ai/docs/ Merge (Phase 22.3d)

**Commits to revert:** Move of `ai/docs/` to `docs/ai_pipeline/` and merge
of `ai/reports/` to `docs/reports/ai_pipeline/`.

**Rollback command:**

```bash
make phase22.rollback STEP=3d
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.3d\|ai/docs" | head -3
git revert --no-edit <commit-hash>

# Restore directory structure
mkdir -p ai/docs ai/reports
git checkout HEAD~1 -- ai/docs/ ai/reports/
```

---

## Step 4: Package Moves (Phase 22.4)

**Commits to revert:** 11 major package moves. Each package move is a separate
commit. Rollback must reverse in reverse order of creation.

**Packages (in reverse rollback order):**

1. `ai/backtest/` → `backtest/`
2. `ai/trc/` → `trc/`
3. `ai/tqu/` → `tqu/`
4. `ai/qid/` → `qid/`
5. `ai/proofreader/` → `proofreader/`
6. `ai/pipeline/` → `pipeline/`
7. `ai/orchestrator/` → `orchestrator/`
8. `ai/nlp/` → `nlp/`
9. `ai/model/` → `model/`
10. `ai/scraper/` → `scraper/`
11. `ai/datasource/enrichment/` → `enrichment/`

**Rollback command (per-package):**

```bash
make phase22.rollback STEP=4a  # backtest
make phase22.rollback STEP=4b  # trc
make phase22.rollback STEP=4c  # tqu
# ... etc for all 11 packages

# Or rollback all at once:
make phase22.rollback STEP=4  # All package moves
```

**Manual rollback (if needed):**

```bash
cd /home/tech/code/negelir
# List all package-move commits
git log --oneline --all --grep="22.4" | head -20

# Revert each commit in reverse order
git revert --no-edit <latest-commit>
git revert --no-edit <prev-commit>
# ... repeat for all 11 package commits

# Clear bytecode
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Re-run full test suite
PYTHONPATH=ai make test
```

**Verification after rollback:**

```bash
# Confirm all ai/ packages are restored
for pkg in scraper model nlp orchestrator pipeline proofreader qid tqu trc backtest; do
  test -d "ai/$pkg" || echo "MISSING: ai/$pkg"
done

# Confirm root packages are gone
for pkg in scraper model nlp orchestrator pipeline proofreader qid tqu trc backtest enrichment; do
  test ! -d "$pkg" && echo "OK: root $pkg removed"
done

# Run isolation check
make isolation.check --full
```

---

## Step 5: Go References (Phase 22.5)

**Commits to revert:** Updates to `server/` Go source for:
- Runtime path constant (`defaultTRNormalizeSpecPath`)
- Parity-test source-path table
- Documentation comments

**Rollback command:**

```bash
make phase22.rollback STEP=5
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.5\|Go.*reference" | head -3
git revert --no-edit <commit-hash>

# Rebuild Go server
cd server && go mod tidy && go build ./cmd/api && cd ..
```

---

## Step 6: Config Migration (Phase 22.6)

**Commits to revert:** Config layer updates:
- `ai/common/config.py` → `common/config/ai_pipeline.py`
- Config key migration documentation
- `CURRENT_SEASON` hardcoding fixes

**Rollback command:**

```bash
make phase22.rollback STEP=6
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.6\|config.*migration" | head -5
git revert --no-edit <commit-hash>

# Restore ai/common/config.py
git checkout HEAD~1 -- ai/common/config.py

# Update root config to re-import from ai
git checkout HEAD~1 -- common/config/__init__.py

PYTHONPATH=ai make test
```

---

## Step 7: Deletion & Shim Cleanup (Phase 22.7)

**Commits to revert:** Deletion of `ai/` and shim cleanup.

**🛑 CRITICAL:** This step deletes the `ai/` directory. Rollback must restore it
from git immediately.

**Rollback command:**

```bash
make phase22.rollback STEP=7
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
# Revert the deletion commit
git log --oneline --all | grep -i "delete ai\|remove ai" | head -1 | awk '{print $1}'
git revert --no-edit <commit-hash>

# Verify ai/ is restored
test -d ai && echo "OK: ai/ restored" || echo "ERROR: ai/ not restored"

# Restore all ai/ files from git
git status | grep deleted | awk '{print $NF}' | while read file; do
  git checkout HEAD -- "$file"
done

# Re-run full test suite against restored layout
PYTHONPATH=ai make test
```

**Verification:**

```bash
# Confirm ai/ structure is intact
find ai/ -type d -maxdepth 1 | wc -l  # Should match baseline

# Confirm isolation gates are green
make isolation.check --full

# Confirm no stale imports
grep -r "from common\." ai/ | grep -v "from ai.common\." | head -5  # Should be minimal
```

---

## Step 8: Snapshot Finalization (Phase 22.8)

**Commits to revert:** Finalization of isolation snapshot after all moves.

**Rollback command:**

```bash
make phase22.rollback STEP=8
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.8\|snapshot.*final" | head -1
git revert --no-edit <commit-hash>

# Restore pre-finalization snapshot
git checkout HEAD~1 -- common/isolation/import_graph.snapshot.json

make isolation.check --full
```

---

## Step 9: Metric Names (Phase 22.9)

**Commits to revert:** Metric name standardization and `ai_` prefix removal.

**Rollback command:**

```bash
make phase22.rollback STEP=9
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.9\|metric.*name" | head -2
git revert --no-edit <latest-commit>
git revert --no-edit <prev-commit>

PYTHONPATH=ai python3 -m pytest common/tests/test_telemetry.py -xvs
```

---

## Step 10: Version Bumps (Phase 22.10)

**Commits to revert:** Major version bumps (1.0.0) for all components that reached
production stability.

**Rollback command:**

```bash
make phase22.rollback STEP=10
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
# Revert version chart update
git log --oneline --all --grep="version.bump.*22.10" | head -1
git revert --no-edit <commit-hash>

# Restore pre-bump versions
git checkout HEAD~1 -- xops/versioning/chart.json

make version.show
```

---

## Step 11: Patcher Artefacts (Phase 22.12)

**Commits to revert:** Phase 17 patcher cassette/bundle path updates (if Phase 17
has shipped; conditional step).

**Rollback command:**

```bash
make phase22.rollback STEP=11
```

**Manual rollback:**

```bash
cd /home/tech/code/negelir
git log --oneline --all --grep="22.12\|patcher.*artefact" | head -2
git revert --no-edit <commit-hash>

# Verify cassette/bundle manifests are valid
ls -la xops/patcher/cassettes/ 2>/dev/null && echo "Cassettes present" || echo "Cassettes not present (expected if Phase 17 unshipped)"
```

---

## General Rollback Procedure (if make target fails)

If `make phase22.rollback STEP=N` fails, use this procedure:

```bash
cd /home/tech/code/negelir

# 1. Identify commits to revert (example for STEP 4)
git log --oneline --all --grep="22.4" --reverse | head -20

# 2. Revert in reverse chronological order
git revert --no-edit <latest-commit-hash>
git revert --no-edit <previous-commit-hash>
# ... repeat for all commits in the step

# 3. Resolve conflicts if they occur
# For each conflict:
#   - Review the conflicting file
#   - Manually pick the pre-migration version (usually the right choice)
#   - git add <file>
#   - git commit --no-edit

# 4. Clean up bytecode
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete

# 5. Re-run tests
PYTHONPATH=ai make test
PYTHONPATH=. make isolation.check --full

# 6. If tests pass, declare rollback complete
echo "Rollback STEP=N complete; all tests green"

# 7. If tests still fail, this indicates:
#    - Either the rollback was incomplete (check git log)
#    - Or the pre-rollback state was already broken (check git blame)
#    - Escalate to the next tier for investigation
```

---

## Emergency Escalation Procedure

If a rollback fails twice in the same step without a successful fix:

1. **Pause the migration** — do not attempt further rollbacks in the same step.
2. **Document the failure** — record the step number, error message, and git
   commit hashes in a tracker row:
   ```bash
   make track.add PHASE=22 STATUS=blocked NOTE="Rollback STEP=N failed twice; investigating <error_message>"
   ```
3. **Escalate to Phase 22 review** — flag for human review before restarting
   the migration or attempting a different strategy.
4. **Never force-push or rebase** — this makes rollback recovery much harder.

---

## Burn-in Monitoring (Phase 22.13)

The burn-in phase is **read-only** — it does not involve code changes. If
metric anomalies are detected during burn-in:

1. Check `make phase22.burn-in.status` for the five counter totals.
2. Investigate each anomaly:
   - Isolation regressions → check `make isolation.check --full`
   - `ai.` import errors → grep logs for stale imports
   - Resurrections → check if any `import ai` code is unexpectedly active
   - Metric-name violations → grep for non-conforming metric names
   - Rollback invocations → review the rollback runbook logs

3. If the issue is genuine (not a fluke):
   - Determine which step introduced the regression
   - Execute a rollback to that step
   - Fix the underlying issue
   - Re-apply the step

---

## Testing a Rollback Locally (Dry-Run)

To test the rollback procedure without actually committing changes:

```bash
cd /home/tech/code/negelir

# 1. Create a test branch at the current HEAD
git branch test-rollback-step-N

# 2. Attempt the rollback on the test branch
git checkout test-rollback-step-N
make phase22.rollback STEP=N

# 3. If successful, test suite should pass
PYTHONPATH=. make test

# 4. If it passes, the rollback procedure is valid
# If it fails, debug before applying to main

# 5. Clean up the test branch
git checkout <original-branch>
git branch -D test-rollback-step-N
```

---

## Summary

Each Phase 22 step has a corresponding rollback procedure. The sequence is:
1. Revert commits in reverse chronological order
2. Clean up generated artefacts
3. Re-run tests and isolation checks
4. Verify the pre-migration state is restored

This runbook should be tested before and after each step to ensure smooth rollback
in case of emergency.
