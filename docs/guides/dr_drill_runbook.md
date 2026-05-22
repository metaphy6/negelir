# Disaster-Recovery Drill Runbook (Phase 8 §8.12)

> **Status:** binding operator procedure for quarterly DR drills.
> Mirrors the Phase 8 §8.12 ROADMAP bullet on "DR drill cadence".
>
> **Audience:** on-call operator with shell access to a host that
> can reach the offsite backup storage and provision a scratch
> Postgres instance in a second region or datacenter.
> Do NOT run any of these flows from a developer laptop.

---

## 0. Doctrine refresher

* **Quarterly cadence.** A DR drill must be recorded in
  `data/backups/dr_drills.csv` at most every 91 days.  The
  `maint_backup_dr_drill_age_days` gauge alerts at 100 days
  (`cfg.maint_backup_dr_drill_alert_days`), giving a ~9-day
  grace window before the on-call is paged.
* **Separate failure domain.** The drill target must be a
  fresh Postgres instance in a **different region or datacenter**
  from the primary.  Restoring to the same host that runs
  production defeats the purpose.
* **Offsite restore only.** The drill verifies the offsite
  copy, not the on-host dump.  Always pass `FROM_OFFSITE=1`.
* **No promotion.** The restored database is ephemeral.
  Promoting it to "live" is outside the scope of this runbook
  and requires a separate, platform-specific change procedure.

---

## 1. Pre-drill checklist

Before you start:

- [ ] Offsite backup is current:
  `maint_backup_offsite_age_hours` < `cfg.maint_backup_offsite_age_alert_h` (default 48 h).
- [ ] A scratch Postgres instance is available in a separate region
  (record its DSN as `DR_CONN`).
- [ ] You have the DR-class decryption key available
  (`cfg.maint_backup_encryption_key_dir`).
- [ ] `make ops.restore` token generation succeeds in `DRY_RUN=1` mode.

---

## 2. Step-by-step DR drill procedure

### Step (a) — Provision a fresh Postgres instance

Provision a Postgres 16 instance in a separate region or
datacenter.  Record its connection string (e.g.
`postgresql://negelir:PASS@dr-host:5432/negelir_dr`) as
`DR_CONN`.

```bash
export DR_CONN="postgresql://negelir:PASS@dr-host:5432/negelir_dr"
export DRILL_DATE="YYYY-MM-DD"   # date of the dump to restore
```

### Step (b) — Restore from offsite backup

```bash
# Dry-run first (confirms token is valid; does NOT restore)
make ops.restore \
  DATE="${DRILL_DATE}" \
  TARGET="${DR_CONN}" \
  FROM_OFFSITE=1 \
  REASON="quarterly-dr-drill" \
  DRY_RUN=1

# Real restore (omit DRY_RUN)
make ops.restore \
  DATE="${DRILL_DATE}" \
  TARGET="${DR_CONN}" \
  FROM_OFFSITE=1 \
  REASON="quarterly-dr-drill" \
  CONFIRM=<typed-token-from-dry-run>
```

Wait for `backup_restore_completed{outcome=ok}` in the audit log
before proceeding.

### Step (c) — Run verification probes

```bash
psql "${DR_CONN}" -f xops/backup/verify.sql
```

Compare row counts against the source database census
(available in the `backup_restore_completed` event's
`verify_summary` field).  All tables must be within the
expected range; `_schema_max_version` must match exactly.

### Step (c2) — Verify per-file manifest integrity

If the dump was created with the §8.14.2 per-file checksum manifest
(`negelir.files.sha256.txt` inside the dump directory), verify it now:

```bash
# Extract the dump directory (if it is in tar+age form, age-decrypt + untar first)
# Then, inside the extracted pg_dump directory:
sha256sum --check negelir.files.sha256.txt
```

Expected output: every line ends with `OK`.  Any `FAILED` line
indicates dump corruption **before** the outer tar — this is a
`kind=backup_dump_file_corrupted` event and the drill result is
**FAILED**.

If the dump pre-dates §8.14.2 (i.e. `negelir.files.sha256.txt` is
absent), the agent emits `kind=backup_legacy_no_file_manifest` and
falls back to outer-tarball-checksum-only verification.  Record
`per_file_manifest=absent` in the drill CSV notes column.

Append a row to `data/backups/dr_drills.csv`:

```
drill_date_utc,outcome,restored_from_offsite,target_conn_hash,drill_duration_s,operator,notes
```

Fields:

| Field | Value |
|---|---|
| `drill_date_utc` | ISO-8601 UTC date/time of the drill (e.g. `2026-05-21T10:00:00Z`) |
| `outcome` | `ok` if verify probes passed; `failed` or `aborted` otherwise |
| `restored_from_offsite` | `1` (always `1` for a DR drill) |
| `target_conn_hash` | SHA-256 of `${DR_CONN}` (first 12 hex chars) — never the literal DSN |
| `drill_duration_s` | Wall-clock seconds from restore start to verify complete |
| `operator` | Your identity (no passwords, no emails) |
| `notes` | Optional short narrative |

Example successful row:

```
2026-05-21T10:00:00Z,ok,1,a3f1b2c4d5e6,1847,ops-oncall,verify passed; 9 tables matched
```

---

## 3. After the drill

1. **Destroy the scratch instance.** Do not leave ephemeral DR
   databases running.
2. **Commit `data/backups/dr_drills.csv`** with message
   `"chore: record DR drill YYYY-MM-DD"` via `make git`.
3. **Verify the gauge resets:**
   ```bash
   python3 -c "
   from xops.backup.dr_drill_gauge import compute_dr_drill_age
   r = compute_dr_drill_age('data/backups/dr_drills.csv')
   print(r.severity, r.age_days)
   "
   ```
   Expect `ok <N>` where N < `cfg.maint_backup_dr_drill_alert_days`.

---

## 4. Gauge and alerting reference

| Metric | Description | Alert threshold |
|---|---|---|
| `maint_backup_dr_drill_age_days` | Days since last successful DR drill | 100 d (`cfg.maint_backup_dr_drill_alert_days`) |

Alert emitted as:
```
sec.alert.v1{kind=backup_dr_drill_overdue, age_days=<N>, severity=critical}
```

The `maint_backup_dr_drill_age_days` gauge reads from
`cfg.maint_backup_dr_drill_csv` (default
`data/backups/dr_drills.csv`).  The gauge module lives at
`xops/backup/dr_drill_gauge.py`.
