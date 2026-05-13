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
