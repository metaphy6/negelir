# Phase 18 Isolation Rollback Runbook

**Phase:** 18.1 §18.1 Isolation contract & policy file  
**Ledger:** #20  
**Author:** Phase 18 implementation  
**Date:** 2026-06-15  
**Status:** Active (for emergency use only)

## Overview

This runbook describes the five-step rollback procedure for isolation enforcement gates in Phase 18. It is intended for use only when an isolation breakage must be urgently relaxed due to a production emergency, and normal resolution is infeasible within the emergency window.

**Prerequisite:** This runbook is only valid if at least one component has `RELAX_ISOLATION_FOR_ROLLBACK=1` set in their environment.

## Five-Step Rollback Procedure

### Step 1: Declare the Emergency

Before invoking the escape hatch, document the incident:

```bash
# Write a brief incident summary to a timestamped file
INCIDENT_ID=$(date +%s)
cat > /tmp/isolation-rollback-$INCIDENT_ID.txt <<EOF
Incident ID: $INCIDENT_ID
Timestamp: $(date --iso-8601=seconds)
Component: <component_name>
Reason: <brief reason for rollback>
Expected duration: <estimated time to resolve>
Approver: <your name/email>
EOF
```

**Document this in on-call channel** (Slack #incidents or equivalent) with the incident ID.

### Step 2: Set the Escape Hatch

Set the environment variable on affected services:

```bash
# For a single service in docker-compose:
RELAX_ISOLATION_FOR_ROLLBACK=1 docker-compose up <service>

# For Kubernetes:
kubectl set env deployment/<component>-deployment   RELAX_ISOLATION_FOR_ROLLBACK=1   -n negelir

# For systemd services:
sudo systemctl set-environment RELAX_ISOLATION_FOR_ROLLBACK=1
sudo systemctl restart <component>.service
```

The isolation checker will continue to run but will not enforce violations. Every check run will emit a security alert with `kind=isolation_relaxed_for_rollback`.

### Step 3: Monitor the Alert Stream

Verify that the escape hatch is active by monitoring the security alert stream:

```bash
# Check recent security alerts (requires access to metrics/logs)
journalctl -u negelir-isolation-checker -f | grep "isolation_relaxed_for_rollback"

# Or via metrics API:
curl -s http://localhost:9090/query?query=isolation_relaxed_for_rollback_total | jq .
```

Each alert includes:
- Timestamp of the check run
- Which isolation violations were relaxed
- Duration remaining until auto-unset

### Step 4: Resolve the Underlying Issue

While the hatch is active, proceed to fix the underlying isolation violation:

1. Identify the violated import or interface
2. Either:
   - Fix the code (preferred): move the import to allowed location, use a shim, refactor the interface
   - Or document the exception: if a violation is legitimate, update `common/isolation/policy.yaml` with proper justification and CODEOWNERS approval
3. Land the fix via the normal `git` → CI → merge flow

**Note:** The hatch will auto-unset after `cfg.isolation_relax_max_hours` (default 72 hours). If your fix is not ready by then, you must go through Step 2 again.

### Step 5: Unset the Escape Hatch

Once the fix is in place and merged, unset the escape hatch:

```bash
# For docker-compose:
docker-compose down
docker-compose up <service>  # Restarts without the env var

# For Kubernetes:
kubectl set env deployment/<component>-deployment   RELAX_ISOLATION_FOR_ROLLBACK-    -n negelir

# For systemd:
sudo systemctl unset-environment RELAX_ISOLATION_FOR_ROLLBACK
sudo systemctl restart <component>.service
```

Verify the hatch is unset by checking the alert stream — it should stop emitting `isolation_relaxed_for_rollback` alerts.

## Observability

### Alerts Emitted

While the escape hatch is active, the checker emits bus event:

```
sec.alert.v1 {
  kind: "isolation_relaxed_for_rollback",
  severity: "alert",
  component: "<component>",
  message: "Isolation enforcement relaxed by escape hatch",
  timestamp: "2026-06-15T12:34:56Z",
  ttl_seconds: <remaining_seconds_until_auto_unset>,
  violated_imports: [
    { file: "...", line: 123, import: "...", target: "..." },
    ...
  ]
}
```

### Metrics

Counters incremented on every check run while active:

- `isolation_relaxed_for_rollback_total{component}` — total times hatch was applied
- `isolation_relaxed_for_rollback_current{component}` — currently active (0 or 1)
- `isolation_relaxed_for_rollback_expires_at{component}` — Unix timestamp of auto-unset

### Logs

Every isolation check logs to structured output while hatch is active:

```json
{
  "level": "warning",
  "msg": "Isolation check run with RELAX_ISOLATION_FOR_ROLLBACK active",
  "component": "datasource",
  "violations_detected": 5,
  "violations_relaxed": true,
  "escape_hatch_expires_at": "2026-06-18T12:34:56Z",
  "escape_hatch_remaining_seconds": 259200
}
```

## Limits & Safeguards

1. **Max Duration:** The hatch auto-unsets after `cfg.isolation_relax_max_hours` (default 72 hours). It cannot be extended; you must go through the full Step 2–5 cycle again.
2. **Audit Trail:** All uses of the hatch are logged to `xops/evidence/isolation-rollback/<incident-id>.json.gz` for post-incident review.
3. **No Silent Bypass:** The hatch does not hide violations — it only suppresses enforcement. Violations are still detected and logged.
4. **Operator Approval:** Setting the hatch requires operator access to the environment (kubectl, systemctl, docker-compose, etc.).

## Incident Review Checklist

After resolving the underlying issue and unsetting the hatch, complete this checklist:

- [ ] Incident ID documented in on-call channel
- [ ] Escape hatch duration < 72 hours (no second hatch needed)
- [ ] Underlying fix merged and deployed
- [ ] Alert stream confirms hatch is unset
- [ ] Post-incident review document written: `docs/incidents/phase18-isolation/<incident-id>.md`
  - Include: root cause, fix applied, prevention measure, approval from security reviewer

## Related Documentation

- [`docs/design/COMPONENT_LAYOUT.md`](../../design/COMPONENT_LAYOUT.md) — component ownership
- [`common/isolation/policy.yaml`](../../common/isolation/policy.yaml) — isolation policy
- [`docs/design/SCRAPER_PATCHER.md`](../../design/SCRAPER_PATCHER.md) — Phase 17 auto-patcher (integrates with Phase 18 gates)

---

## Quarterly Drill Checklist

**Run quarterly (every 3 months) to validate the runbook is accurate and operators are trained.**

### Pre-Drill (1 day before)

- [ ] Schedule 30-minute maintenance window in on-call calendar
- [ ] Notify team in #incidents channel: "Phase 18 isolation rollback drill scheduled for [date/time]"
- [ ] Confirm ephemeral test environment is ready (isolated from production)
- [ ] Review the five-step procedure (above) — any updates needed?

### Drill Execution (30 minutes)

- [ ] **Step 1:** Create a dummy incident ID and document it: `DRILL_INCIDENT_ID=$(date +%s)_drill`
- [ ] **Step 2:** Set the escape hatch on the test environment: `RELAX_ISOLATION_FOR_ROLLBACK=1`
- [ ] **Step 3:** Verify alerts are emitted correctly in test logs
- [ ] **Step 4:** Simulate a fix: modify a test file to remove the isolation violation
- [ ] **Step 5:** Unset the hatch: `RELAX_ISOLATION_FOR_ROLLBACK-` or restart services
- [ ] **Verify:** Confirm hatch is unset (no more alerts in test logs)

### Post-Drill (same day)

- [ ] Log drill results: `docs/tracking/drills.csv` (use `make track.add PHASE=18 STATUS=in-progress NOTE="rollback drill executed, all 5 steps passed"`)
- [ ] Document any issues or clarifications needed in runbook
- [ ] Post summary in #incidents: "✅ Phase 18 rollback drill completed. All steps passed."
- [ ] Update this checklist if procedures changed

### Drill Success Criteria

- ✅ All five steps completed without errors
- ✅ Escape hatch activates and deactivates cleanly
- ✅ Alerts emit at the correct times
- ✅ Drill log entry committed to `docs/tracking/drills.csv`

### Drill Failure Response

If any step fails:
1. Document the failure: `xops/evidence/drill-failures/<date>_rollback_drill.md`
2. Escalate to Phase 18 implementation lead
3. Schedule a retrospective within 48 hours
4. Do **not** re-run the drill until the failure is resolved

**Missed Drill Consequence:** Per ROADMAP Phase 18.9, two consecutive missed quarterly drills trigger removal of the `RELAX_ISOLATION_FOR_ROLLBACK` hatch (closing the door behind us). This is automatic and cannot be waived.
