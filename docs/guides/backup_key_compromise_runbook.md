# Encryption-Key Compromise Runbook (Phase 8 §8.13.6)

> **Status:** binding contract for encryption-key incident response.
> Mirrors the Phase 8 §8.13.6 ROADMAP bullet.
>
> **Audience:** on-call operator with write access to the backup-keys
> repository path and authority to publish `maint.event.v1`. Do NOT
> run any of these flows from a developer laptop or an automated job.

---

## 0. Doctrine refresher

* **Two key classes, two roles.** The *verify key* is a per-dump
  ephemeral keypair used only during the nightly restore-verify
  pass. The *DR keys* are long-lived recipient set used for
  production restores. A compromise of one class does NOT implicate
  the other.
* **No automation decides on deletions.** Every step here that
  involves potentially deleting backup objects requires an explicit
  operator decision. Automation can revoke and rotate; it can flag
  objects for review. It cannot delete.
* **Object-Lock window.** Offsite dumps are written with an
  Object-Lock retention period. Deletion requests inside the window
  are silently ignored by the object store. After expiry, manual
  pruning is allowed but still operator-driven.
* **Emit the acknowledgement event.** Every scenario ends with an
  audit event so the incident is on the `maint.event.v1` record.

---

## 1. Verify-class key compromise

### Impact

Scoped to **at most one dump per backup run**. The verify keypair is
generated fresh for each nightly cycle (§8.3 per-dump rotation
policy). A compromised verify key grants access to one dump, and
only during the window between its generation and its scheduled
post-verify deletion. The DR-class encryption of the same dump is
entirely unaffected; data recovery capability is not degraded.

### Procedure

1. **Rotate the verify key immediately.**

   ```
   ops.backup-rotate-key --scope verify
   ```

   This regenerates the verify keypair and removes the old Secret.
   No further access to the old key is possible after this point.

2. **Identify the affected dump.** The dump whose nightly
   restore-verify cycle used the compromised verify key is at most
   the most-recent one. Check the nightly log for the
   `backup_restore_verify_completed` event; the `dump_date` field
   identifies it.

3. **Re-encryption happens automatically.** During the *next*
   nightly's restore-verify pass the affected dump is decrypted via
   the surviving DR-class key and re-encrypted to the fresh verify
   key. No manual step is required.

4. **No data loss possible.** The DR-class encryption of every dump
   is intact. Recovery capability is unaffected.

5. **Emit audit event.**

   ```
   ops.maint-emit \
     kind=backup_key_compromise_acknowledged \
     scope=verify \
     action=rotate \
     note="verify key compromise; rotated; re-encryption scheduled"
   ```

---

## 2. DR-class key compromise (single recipient of N)

### Impact

The compromised private key can decrypt **every dump** that was
encrypted to that recipient (which is all dumps produced while the
key was in the recipient set). The surviving DR recipients are
unaffected. Recovery capability is not lost as long as at least one
uncompromised DR recipient remains.

### Procedure

1. **Revoke the compromised recipient immediately.**

   Edit `infra/maint/backup_keys/dr/recipients.txt`. Remove the
   line containing the compromised public-key fingerprint. Commit
   the change with a message referencing the incident ID.

   ```
   # remove compromised-key-fingerprint from recipients.txt
   git add infra/maint/backup_keys/dr/recipients.txt
   # commit via make git — human-only step
   ```

2. **Add a fresh DR recipient and rotate.**

   ```
   ops.backup-rotate-key \
     --scope dr \
     --add-recipient <new-public-key-armored-or-fingerprint>
   ```

   This updates the active recipient set for all future dumps. The
   next nightly backup will be encrypted to the new set only.

3. **Old dumps are NOT re-encrypted.** Re-encrypting multi-month
   archives is computationally prohibitive. Existing dumps remain
   decryptable by all original recipients — including the compromised
   one — and by all surviving recipients. Treat the archive as
   "trusted but compromised": the data can be read by the threat
   actor if they hold the private key.

4. **Decide on affected dump retention.** The operator, not
   automation, decides whether to delete the affected dumps:

   * Dumps inside the Object-Lock retention window **cannot** be
     deleted (the object store will ignore the request).
   * After the retention window expires, the operator may prune
     dumps that were accessible to the compromised key. This is a
     manual step — no automated job will do this.
   * Document the decision in the incident record and in
     `data/maint/dr_drills.csv` (add a row with
     `event=key_compromise_acknowledged, scope=dr, disposition=<keep|prune>`).

5. **Emit audit event.**

   ```
   ops.maint-emit \
     kind=backup_key_compromise_acknowledged \
     scope=dr \
     recipient_fingerprint=<compromised-fingerprint> \
     action=revoke \
     note="single-recipient DR key compromise; revoked; new recipient added"
   ```

---

## 3. Full DR-class compromise (all N recipients)

### Impact

**Catastrophic.** Every dump in the archive is accessible to the
threat actor. The entire DR key set must be rotated before a new
safe backup can be taken.

### Procedure

1. **Stop scheduled backups immediately** (to avoid producing new
   dumps encrypted to the compromised keys):

   ```
   ops.maint-disable-backups --reason=key_emergency
   ```

2. **Rotate ALL DR recipients in one operation.**

   Clear `infra/maint/backup_keys/dr/recipients.txt` and replace
   with new public keys. Then:

   ```
   ops.backup-rotate-key \
     --scope dr \
     --replace-all \
     --recipients-file infra/maint/backup_keys/dr/recipients.txt
   ```

   This sets the active recipient set to the new keys only.

3. **Trigger an emergency nightly backup.**

   ```
   ops.backup-now --reason=key_emergency
   ```

   The resulting dump will be encrypted to ONLY the new DR keys.
   This establishes the first clean backup post-compromise.

4. **Flag old dumps for risk review.** Add a row to
   `data/maint/dr_drills.csv` for every dump produced before the
   rotation timestamp, with status `compromised_key_set`:

   ```
   date,event,scope,disposition,operator,note
   <YYYY-MM-DD>,key_compromise_full_dr,dr,pending_review,<operator-id>,all N DR recipients compromised
   ```

   No automation updates this file. Operator fills it.

5. **Decide on affected dump retention.** Same constraints as
   §2 step 4, amplified: *every* dump before the rotation is
   accessible to the threat actor. The operator reviews the
   risk and records a decision per dump set:

   * Inside Object-Lock window → cannot delete; document for
     post-window review.
   * After window → operator prunes or retains; document in
     `dr_drills.csv`.

   **No automation decides whether to delete old dumps.
   This is an operator-only call.**

6. **Re-enable scheduled backups** once step 2–3 are confirmed:

   ```
   ops.maint-enable-backups
   ```

7. **Emit audit event.**

   ```
   ops.maint-emit \
     kind=backup_key_compromise_acknowledged \
     scope=dr \
     action=full_rotate \
     note="all DR recipients compromised; full rotation completed; emergency backup triggered"
   ```

---

## 4. Quick-reference table

| Class | Max dumps at risk | Re-encrypt old dumps | Automated recovery |
|---|---|---|---|
| Verify | 1 | Yes (next nightly) | Yes |
| DR single | All in archive | No | Rotation only |
| DR full | All in archive | No | Rotation only |

In all three cases:
- The operator records the incident in `dr_drills.csv`.
- The `backup_key_compromise_acknowledged` event must be emitted
  before closing the incident ticket.
- Old-dump deletion is always an operator-only decision.
