# Backup & Restore Runbook (Phase 8 §8.3)

> **Status:** binding contract for the operator-driven restore
> path (`ops.restore`). Mirrors the Phase 8 §8.3 ROADMAP bullet
> on "Restore runbook (`ops.restore` — binding)".
>
> **Audience:** on-call operator with shell access to a host that
> can publish onto the `maint.event.v1` topic and reach the
> backup directory (or its off-host replica). Do NOT run any of
> these flows from a developer laptop.

---

## 0. Doctrine refresher (before you touch anything)

* **Operator-driven, never automated.** `ops.restore` is the only
  legal entry point; there is no scheduled job that will quietly
  restore production for you. The command is in
  `ALWAYS_DESTRUCTIVE` and gates every invocation through the
  Phase 8 §8.1 typed-token preimage.
* **Default destination is ephemeral.** Without
   `TARGET=...`, the consumer (`maint.backup.v1`)
  resolves the target to `negelir_restore_<dump_date>`. The
  operator promotes that database to "live" by hand, in a
  separate step that is NOT covered by this runbook (because the
  promotion semantics depend on the deployment platform).
* **Live primary requires two flags.** Pointing
   `TARGET` at the live application Postgres AND
  passing `CONFIRM_OVERWRITE_LIVE=1` are both required; the
  consumer refuses with `live_overwrite_requires_confirm`
  otherwise. A typed `--confirm` token alone is not enough.
* **DR-class private key only.** The decryption gate rejects
  verify-class keys with the surface code `dr_key_required`.
  The verify-class key (rotated per dump) is for restore-verify
  only; it is intentionally short-lived and grants access to at
  most one dump.

If you are not sure whether you need this runbook, page the
on-call backup owner first. Don't experiment in production.

---

## 1. Anatomy of one `ops.restore` invocation

```bash
make ops.restore \
   DATE=YYYY-MM-DD \
   [TARGET=<postgres-dsn>] \
    [CONFIRM_OVERWRITE_LIVE=1] \
    [FROM_OFFSITE=1] \
    [REASON="<short narrative>"] \
    CONFIRM=<typed-token> \
    DRY_RUN=1
```

The publisher (`xops/opsctl/subcommands/restore.py`) folds
`destination_conn`, `from_offsite`, and `confirm_overwrite_live`
into the `--confirm` typed-token preimage. **Dropping any of
those flags between a `DRY_RUN=1` rehearsal and the real run
will INVALIDATE the token** — by design, so the operator cannot
accidentally promote a DR-drill confirmation into a production
overwrite.

The consumer (`MaintBackupAgent._handle_restore`) emits two
events to `maint.event.v1` AND mirrors both to `maint_audit_log`:

| Event | When | Notes |
|---|---|---|
| `backup_restore_started` | After all gates pass; before the executor runs | Carries `target`, `dump_date`, `requested_by`, `ephemeral`, `destination_conn`. |
| `backup_restore_completed` | When the executor returns (or raises) | Carries `exit_code`, `outcome`, `duration_ms`, optional `verify_summary`. |

A failed gate emits a refusal `maint.ack.v1` plus a
`backup_restore_completed{outcome=...}` (no `started` event —
the restore was never attempted). The `outcome` taxonomy is
closed (`xops/opsctl/_classify.py` defines the destructive set;
the agent pins the outcomes in `RESTORE_OUTCOMES`).

Outcome surface tokens:

* `ok` — restore succeeded; `verify_summary` populated.
* `dr_key_required` — verify-class key was offered.
* `live_overwrite_requires_confirm` — live-DSN destination
  without `--confirm-overwrite-live`.
* `decrypt_failed` — no DR key class resolved for the dump
  (e.g. all DR-class private halves are off-cluster, which is
  the steady state — see scenario A).
* `restore_failed` — `pg_restore` returned non-zero or the
  executor raised.
* `post_verify_failed` — `pg_restore` succeeded but
  `xops/backup/verify.sql` returned an empty row-count map.

---

## 2. Worked scenarios

### Scenario A — DR from off-site replica (cold start)

The active cluster's PVC was lost; the only intact dump lives
on the off-host replica configured per ROADMAP §8.12. You are
restoring into a fresh ephemeral target on a freshly provisioned
host.

1. **Confirm the off-site dump is reachable.** From the new
   host, run `make mock.verify` (compose mode) or `xops/backup`
   inventory tooling to list the dumps the replica advertises.
2. **Provision the DR-class private half.** Per the §8.3 binding,
   DR-class private keys live strictly off-cluster. Decrypt the
   sealed envelope (paper / hardware token / KMS) and place the
   identity file at `cfg.maint_backup_age_identity_file`. **This
   is the only step where a DR-class private half ever touches a
   filesystem; revoke / re-seal it the moment the restore
   finishes.**
3. **Dry-run the restore to see the envelope and token.**
   ```bash
      make ops.restore DATE=2026-04-30 FROM_OFFSITE=1 \
       REASON="DR cold start: cluster A lost" \
       DRY_RUN=1
   ```
   Copy the `confirm_token` from the output.
4. **Execute.** Re-run with `DRY_RUN` removed and `CONFIRM=<token>`
   appended. Default destination = `negelir_restore_2026-04-30`.
5. **Watch for `backup_restore_completed{outcome=ok}`** on the
   bus or in `maint_audit_log`. Investigate any non-ok outcome
   before promoting.
6. **Promote the ephemeral DB to live.** This is platform-specific
   (rename in psql; cut over the app's DSN; etc.) and outside
   this runbook.

### Scenario B — Point-in-time from on-host archive

A regression landed yesterday and you need to compare today's
data to last Tuesday's snapshot. You are restoring into a
side-by-side DB on the same host so you can `psql` into both at
once.

1. **List local dumps.** `ls -1 $NEGELIR_MAINT_BACKUP_DIR`.
2. **Pick the date.** Confirm the dump is "verified" by checking
   the most recent `backup_completed{verified:true}` event for
   that dump_date.
3. **Dry-run + execute.**
   ```bash
      make ops.restore DATE=2026-04-23 \
       REASON="point-in-time compare for incident #482" \
       DRY_RUN=1
      make ops.restore DATE=2026-04-23 \
       REASON="point-in-time compare for incident #482" \
       CONFIRM=<token>
   ```
4. The default ephemeral target is `negelir_restore_2026-04-23`.
   Connect with `psql -d negelir_restore_2026-04-23` and diff
   against live.
5. **Drop the ephemeral DB when done.** This is a manual cleanup
   step — the runbook deliberately does NOT auto-drop, so the
   operator can decide whether the restore is still useful.

### Scenario C — Accidental table drop on the live primary

A migration dropped `pattern_allowlist` rows that should not have
been dropped. You need to restore yesterday's data into the live
primary because no other recovery path exists.

⚠️ **This is the only scenario where `CONFIRM_OVERWRITE_LIVE=1`
is justified.** Get a second operator's sign-off first, in
writing, on the on-call channel.

1. **Quiesce the writers.** Pause the source agents writing to
   `pattern_allowlist` (`make ops.maint-pause TARGET=maint.sec.v1`).
2. **Dry-run with the live DSN AND the live-overwrite flag.**
   ```bash
      make ops.restore DATE=2026-04-29 \
         TARGET="$NEGELIR_MAINT_BACKUP_PG_DSN" \
       CONFIRM_OVERWRITE_LIVE=1 \
       REASON="incident #491: restore pattern_allowlist; second-op approval @<handle>" \
       DRY_RUN=1
   ```
3. **Execute** with the printed token. The consumer will refuse
   with `live_overwrite_requires_confirm` if you forget the
   `CONFIRM_OVERWRITE_LIVE=1` flag — that refusal is BY DESIGN
   and lands in `maint_audit_log`.
4. **Verify post-restore.** The consumer runs `xops/backup/verify.sql`
   automatically; check `backup_restore_completed.verify_summary`
   matches expectations before you `make ops.maint-resume` the
   paused agents.
5. **Document the run** in the incident channel and reference the
   `request_id` from `backup_restore_completed`.

---

## 3. Failure-mode quick reference

| Symptom | Likely surface | What to do |
|---|---|---|
| `acks[0].reason == "dr_key_required"` | A verify-class key was wired into the restore path | Re-provision the DR-class identity; never re-use a verify key. |
| `acks[0].reason == "live_overwrite_requires_confirm"` | `TARGET` matched the live DSN without the live-overwrite flag | Re-issue with `CONFIRM_OVERWRITE_LIVE=1` (and second-op approval). |
| `outcome == "decrypt_failed"` | No DR-class key file resolved | Check `cfg.maint_backup_age_identity_file` exists and is readable by the agent process. |
| `outcome == "restore_failed"` (`exit_code != 0`) | `pg_restore` died | Inspect agent logs for the captured stderr; check disk pressure on the destination. |
| `outcome == "post_verify_failed"` | `pg_restore` finished but `verify.sql` returned empty | Likely a partial restore or a destination DB the verify role cannot reach. Re-run with a clean destination. |

---

## 4. Cross-references

* **Doctrine:** `AGENTS.md` §1 (no git in agent loops),
  §6.1 (versioning), §3 (tracker rows).
* **Schemas:** [`ai/swarm/sdk/schemas/maint.event.v1/restore.json`](../../ai/swarm/sdk/schemas/maint.event.v1/restore.json),
  [`backup_restore_started.json`](../../ai/swarm/sdk/schemas/maint.event.v1/backup_restore_started.json),
  [`backup_restore_completed.json`](../../ai/swarm/sdk/schemas/maint.event.v1/backup_restore_completed.json).
* **Verify SQL:** [`xops/backup/verify.sql`](../../xops/backup/verify.sql).
* **Recipient classifier:** [`xops/backup/recipients.py`](../../xops/backup/recipients.py).
* **Consumer code:** [`ai/swarm/agents/maint/backup.py`](../../ai/swarm/agents/maint/backup.py)
  (`_handle_restore`).

---

## 5. `age` binary install and version pinning

The backup agent encrypts and decrypts dump archives with
[`age`](https://age-encryption.org/).  The agent **refuses to start** if
the installed binary's self-reported version does not match
`cfg.maint_backup_age_binary_version` (default `"1.2.0"`); a mismatch
emits `sec.alert.v1{kind=fail_safe_age_version_mismatch_local, severity=critical}`.

### 5.1 Install the pinned version

```bash
# Linux x86-64 — replace with the correct arch for your build
AGE_VERSION="$(PYTHONPATH=ai python3 -c 'from common.config import Config; print(Config().maint_backup_age_binary_version)')"
wget -q "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-amd64.tar.gz"
tar -xf "age-v${AGE_VERSION}-linux-amd64.tar.gz"
sudo install -m 0755 age/age age/age-keygen /usr/local/bin/
age --version   # must print v${AGE_VERSION}
```

> **Never** use a package-manager-provided `age` without verifying it
> matches the cfg pin.  Distro packages frequently lag behind or patch
> the binary in ways that invalidate the expected version string.

### 5.2 Bumping the pin (verify-PG version-bump procedure)

When upgrading the source PostgreSQL server (e.g. PG 16 → PG 17):

1. Update `MAINT_BACKUP_VERIFY_PG_IMAGE` in `xops/env/.env.example`
   (and in your active `xops/env/.env`) to match the new major version,
   e.g. `postgres:17-alpine`.
2. Rebuild the SidecarVerifier Job manifest to reference the new image.
3. Run `make ops.backup-bump-age` (if available) **or** update
   `MAINT_BACKUP_AGE_BINARY_VERSION` if you are simultaneously upgrading
   the `age` binary.
4. Verify the agent starts cleanly: check for absence of
   `fail_safe_verify_pg_too_old` and `backup_verify_pg_version_mismatch`
   alerts in the first 60 s after restart.

> The source PG version is read from `negelir.manifest.json`
> (`server_version_num: int` — raw integer from `SHOW server_version_num`).
> The agent boot-validates `verify_pg_image_version_num >= source_server_version_num`.
> A mismatch causes refusal with `fail_safe_verify_pg_too_old` **before**
> any restore attempt touches live data.

### 5.3 Config knobs summary

| Knob | Default | Purpose |
|---|---|---|
| `MAINT_BACKUP_AGE_BINARY_VERSION` | `1.2.0` | Expected `age --version` string.  Agent refuses if mismatched. |
| `MAINT_BACKUP_VERIFY_PG_IMAGE` | `postgres:16-alpine` | Docker image for the ephemeral restore-verify container.  Must be ≥ source PG version. |
| `MAINT_BACKUP_PG_DUMP_NICE_LEVEL` | `10` | `nice` level wrapping `pg_dump` (0 = dev/no contention). |
| `MAINT_BACKUP_PG_DUMP_IONICE` | `true` | Enable `ionice -c 2 -n 7` around `pg_dump` (Linux only). |

---

## 6. Offsite credential rotation and forensic capture (§8.15.10)

### 6.1 Offsite credential rotation

The offsite S3/GCS/B2 credentials stored in the agent's secrets are time-boxed
to `cfg.maint_backup_offsite_credential_max_age_days` (default 90 d).

**Rotation procedure:**

1. On any backup run the agent checks the credential file mtime against the
   threshold.  When age exceeds the threshold it emits
   `sec.alert.v1{kind=offsite_credential_rotation_required, severity=warn}`
   (debounced daily).
2. Operator runs `make ops.rotate-offsite-creds PROVIDER=<s3|gcs|b2>` which:
   a. Generates or imports new credentials.
   b. Writes them to the secrets mount at the path in
      `cfg.maint_backup_offsite_credential_path`.
   c. Emits `maint.event.v1{kind=offsite_creds_rotated}` on the bus.
3. The agent picks up the new credentials on the next run (no restart needed;
   the path is re-read each time).

### 6.2 Forensic capture on verify failure

When `maint.backup.v1` restore-verify encounters a critical check failure
(schema mismatch, row-count anomaly, or HMAC chain break) it triggers a
forensic capture:

1. It writes a `verify_forensic.json` sidecar alongside the failed dump
   directory (renamed to `<date>.failed/verify_forensic.json`).
2. The sidecar is bounded by `cfg.maint_backup_forensic_max_bytes` (default
   262144 bytes = 256 KB).  Content beyond the cap is truncated with a
   `…truncated` sentinel appended.
3. The agent emits `maint.event.v1{kind=verify_forensic_captured}` on the bus
   so operators know the sidecar is available.
4. The verify pass then emits the normal failure alert (e.g.
   `backup_verify_failed`) with `forensic_path` populated.

**Postmortem walkthrough:**

```
data/backups/<date>.failed/
├── <dump>.tar.age         # encrypted archive (may be truncated / absent)
├── <dump>.tar.sha256      # outer checksum
└── verify_forensic.json   # ≤ cfg.maint_backup_forensic_max_bytes
```

Inspect with:

```bash
# Check the forensic sidecar (pretty-print first 50 lines)
cat data/backups/<date>.failed/verify_forensic.json | python3 -m json.tool | head -50
```

Cross-references:
* `verify_forensic_captured` in `KIND_SCHEMA_VERSIONS` →
  [`ai/swarm/sdk/kind_schema_version.py`](../../ai/swarm/sdk/kind_schema_version.py).
* Chaos coverage: `P12-8-AD` (`chaos-verify-concurrency-deadlock`) in
  [`docs/testing/phase12_catalogue.md`](../testing/phase12_catalogue.md).
