# Phase 18 Layout Freeze Runbook

**Phase:** 18 — Datasource Cohesion & Swarm Isolation  
**Ledger:** #21  
**Author:** Phase 18 implementation  
**Date:** 2026-06-15  
**Status:** Active (quarterly freeze window)

## Overview

During Phase 18, the project maintains a **file layout freeze** on component boundaries. New top-level directories, module moves, or cross-component public-surface changes are gated by the `make isolation.status` check and must conform to `COMPONENT_LAYOUT.md`.

This runbook describes the quarterly freeze-audit procedure to ensure layout integrity across the phase and to detect any "shim resurrection" attempts (code added to the `ai/` migration shims after they should have been inert).

**Who runs this:** Phase 18 implementation lead or designated operator (once per quarter, on the quarter boundary).

## Freeze Status

**Freeze Window:** Phase 18.0 → Phase 18.13  
**Freeze Enforcement:** Via `xops/lint/component_path_drift.py` (blocks PRs that violate layout)  
**Break-Glass:** `RELAX_ISOLATION_FOR_ROLLBACK=1` (see [`phase18_rollback.md`](phase18_rollback.md))

## Quarterly Freeze Audit (30 minutes)

Run this on Q1, Q2, Q3, Q4 boundaries to validate layout hygiene.

### Pre-Audit Checklist

- [ ] Schedule 30-minute maintenance window
- [ ] Notify team in #incidents channel
- [ ] Review the audit steps below — any updates needed?

### Step 1: Verify Layout Matches COMPONENT_LAYOUT.md

```bash
# Check that every top-level dir in the layout matches COMPONENT_LAYOUT.md §1
make isolation.status

# Expected output:
#   ✅ datasource/ mapped to COMPONENT_LAYOUT§2
#   ✅ swarm/ mapped to COMPONENT_LAYOUT§3
#   ✅ common/ mapped to COMPONENT_LAYOUT§4
#   ✅ server/ mapped to COMPONENT_LAYOUT§5
```

If any check fails, investigate the diff:

```bash
git diff HEAD -- docs/design/COMPONENT_LAYOUT.md
git log --oneline -10 -- ai/ datasource/ swarm/ common/
```

**Action if failed:** Escalate to Phase 18 implementation lead. The freeze is broken.

### Step 2: Scan for Shim Resurrection

Check that **migration shims** in `ai/` are still inert (no new code added since Phase R2 deployment).

```bash
# List all files under ai/ that should be shims by now
find ai/ -type f -name "*.py" | head -50

# For each non-test, non-generated file, verify it is a shim:
# A shim file has ONE of:
#   (a) imports and re-exports from the new location only
#   (b) a deprecation warning comment at top
#   (c) is in ai/tests/ (allowed to remain)
#   (d) is ai/common/config.py (special case: lives in both layouts)

# Detailed check: look for lines of actual logic (not imports/comments/docstrings)
cd ai && for f in $(find . -type f -name "*.py" | grep -v __pycache__ | grep -v ".pyc"); do
  LINES=$(python3 -c "
import ast
try:
  with open('$f') as fh:
    tree = ast.parse(fh.read(), filename='$f')
    # Count non-trivial statements (excludes imports, docstrings, assignments)
    count = sum(1 for node in ast.walk(tree) 
      if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.For, ast.If, ast.While)))
    print(count)
except: print(-1)
  " 2>/dev/null)
  if [ "$LINES" -gt 5 ]; then
    echo "⚠️  $f has $LINES statements (likely not a shim)"
  fi
done
```

**Action if found:** Raise an incident. New logic in `ai/` during Phase 18 is a layout violation.

### Step 3: Check Transition-Safe Hatch Use

Verify no production deployments are using `RELAX_ISOLATION_FOR_ROLLBACK` outside of active incidents.

```bash
# Query production env for the hatch
kubectl get deployment -A -o json | jq '.items[] | select(.spec.template.spec.containers[].env[] | select(.name=="RELAX_ISOLATION_FOR_ROLLBACK"))'

# Expected: empty (no output means hatch is not set in production)
```

**Action if found:** Investigate the incident. The hatch should auto-unset after 72 hours; if it's older than that, escalate.

### Step 4: Validate ROADMAP Phase 18.* Status

Confirm that ROADMAP.md Phase 18 bullets are in sync with actual code:

```bash
# List all open Phase 18 bullets
grep -A 50 "^## 18" docs/planning/ROADMAP.md | grep "^- \[ \]"

# Cross-check against git history (Phase 18 should have commits in last month)
git log --since="30 days ago" --oneline | grep -i "phase 18\|isolation\|layout\|cohesion" | head -20
```

**Action if many bullets are still open:** Escalate. Phase 18 work may be stalled.

### Step 5: Record the Audit

Log the freeze audit completion:

```bash
make track.add PHASE=18 STATUS=in-progress NOTE="quarterly freeze audit passed, no shim resurrection, no hatch misuse, no layout drift"
```

Update this runbook timestamp: **Last audited: [date]**

### Post-Audit Checklist

- [ ] All five steps completed without errors
- [ ] Layout drift check passed
- [ ] No shim resurrection detected
- [ ] Hatch usage verified (not active in prod)
- [ ] ROADMAP Phase 18 status validated
- [ ] Audit recorded in tracker
- [ ] Team notified in #incidents channel

## Observability

### Metrics

Monitor these metrics (available via `curl localhost:9090/metrics`):

- `phase18_layout_drift_detected_total` — counter incremented when `make isolation.status` detects drift
- `phase18_hatch_usage_total{component}` — counter incremented each time `RELAX_ISOLATION_FOR_ROLLBACK` is set
- `phase18_hatch_current{component}` — gauge (0 or 1) indicating if hatch is currently active
- `phase18_shim_resurrection_detected_total` — counter incremented when new code is found in ai/ shims

### Alerts

If any metric crosses a threshold, a security alert is emitted:

- **`layout_drift`** (severity=critical) — layout mismatch detected
- **`hatch_expired`** (severity=warning) — hatch has been active > 72 hours without unsetting
- **`shim_resurrection`** (severity=critical) — new code detected in ai/ migration shims

### Logs

Every freeze audit run logs to:

```json
{
  "level": "info",
  "event": "phase18_layout_freeze_audit",
  "timestamp": "2026-06-15T12:00:00Z",
  "audit_id": "<uuid>",
  "status": "passed",
  "checks": {
    "layout_matches_doc": true,
    "no_shim_resurrection": true,
    "hatch_not_active_in_prod": true,
    "roadmap_in_sync": true
  }
}
```

## Break-Glass & Incident Response

If any freeze audit check fails **during** Phase 18:

1. **Do not proceed** with any layout changes
2. **Escalate immediately** to Phase 18 implementation lead
3. **Document the failure** in `xops/evidence/freeze-failures/<date>_audit.json`
4. **Review** whether the Phase 18 assumption (frozen layout) is still valid
5. **If valid assumption broken**, mark the freeze as "compromised" and open a retrospective

## Quarterly Schedule

| Quarter | Audit Date | Auditor | Status |
|---------|-----------|---------|--------|
| Q2 2026 | 2026-06-30 | TBD | Pending |
| Q3 2026 | 2026-09-30 | TBD | Pending |
| Q4 2026 | 2026-12-31 | TBD | Pending |
| Q1 2027 | 2027-03-31 | TBD | Pending |

## Related Documentation

- [`docs/design/COMPONENT_LAYOUT.md`](../../design/COMPONENT_LAYOUT.md) — layout frozen until Phase 22
- [`docs/planning/ROADMAP.md`](../../planning/ROADMAP.md) §18 — Phase 18 scope
- [`phase18_rollback.md`](phase18_rollback.md) — break-glass procedure
- `make isolation.status` — real-time layout status

