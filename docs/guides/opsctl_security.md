# Opsctl Security Guide

> **Phase 8 §8.14.4** — Redis ACL setup, signed-envelope key
> generation, and per-subcommand authorisation.
>
> **Audience:** operators bootstrapping a new deployment or rotating
> security material.

---

## 1. Threat model summary

`ops.*` subcommands publish `maint.event.v1` envelopes on the Redis
Streams bus.  The threat surface has two layers:

1. **Bus access** — any process with the Redis password can publish
   arbitrary envelopes.  Mitigated by a dedicated Redis ACL user with
   `NOCOMMANDS` except the exact streams commands `opsctl` requires.
2. **Envelope forgery** — a compromised process with bus write access
   could craft a `maint.event.v1` envelope that looks like an operator
   command.  Mitigated by HMAC-signed envelopes: consumers reject any
   envelope whose `signature` field does not verify against the current
   operator key.

Both layers are independent; both must be in place for production
deployments.  `cfg.opsctl_require_signature=true` (the default) enforces
envelope signing at the consumer side.

---

## 2. Redis ACL setup

### 2.1 Create the `negelir_opsctl` Redis user

```redis
# Run in redis-cli or via make ops.bootstrap-key (if implemented)
ACL SETUSER negelir_opsctl on >REPLACE_WITH_STRONG_PASSWORD \
  ~maint.event.v1 \
  +XADD +XLEN +XRANGE +XREAD +XREADGROUP +XACK
```

> **Never** grant `negelir_opsctl` the `KEYS`, `FLUSHDB`, `FLUSHALL`,
> `CONFIG`, `ACL`, or `DEBUG` commands.

Set `REDIS_OPSCTL_PASSWORD` in `xops/env/.env` to the password chosen
above.  The `opsctl` binary reads it from the environment; it is never
written to disk or logged.

### 2.2 Verify the ACL

```bash
redis-cli --user negelir_opsctl --pass "${REDIS_OPSCTL_PASSWORD}" \
  XLEN maint.event.v1
# Expect: (integer) <N>  — not an AUTH error
```

---

## 3. Signed-envelope key generation

### 3.1 Bootstrap the operator key

```bash
# Generate a 32-byte random key and write it to the canonical path
make ops.bootstrap-key
# OR manually:
python3 -c "import secrets, pathlib; \
  pathlib.Path('infra/maint/opsctl_key.bin').write_bytes(secrets.token_bytes(32))"
chmod 0600 infra/maint/opsctl_key.bin
```

> `infra/maint/opsctl_key.bin` is gitignored.  Back it up in your
> secrets vault.  Loss of the key means opsctl cannot sign new
> envelopes until a replacement key is generated and distributed to
> consumers.

### 3.2 Wire the key path in config

```bash
# xops/env/.env
OPSCTL_KEY_FILE=infra/maint/opsctl_key.bin
```

The key file is read by `xops/opsctl/_sign.py` at publish time and by
the `maint.event.v1` consumer at verify time (consumers also read
`OPSCTL_KEY_FILE`).

### 3.3 Key rotation procedure

1. Generate a new key: `python3 -c "import secrets, pathlib; pathlib.Path('infra/maint/opsctl_key_new.bin').write_bytes(secrets.token_bytes(32))"`.
2. Update `OPSCTL_KEY_FILE` in `xops/env/.env` to point at the new file.
3. Restart all consumer agents (`make down && make up`).
4. Issue a test `ops.status` command and verify no `opsctl_signature_invalid` alert fires.
5. Delete the old key file and remove it from the backup vault entry.

> **Key revocation:** if a key is compromised, set
> `cfg.opsctl_require_signature=true` (default) and replace the key
> immediately.  All envelopes signed with the old key will be rejected
> by consumers once they reload the new key.  Envelopes in
> `data/maint/opsctl_spool/` signed with the old key will also be
> rejected on re-flush — operator must re-issue the commands.

---

## 4. Per-subcommand authorisation file

### 4.1 File location and format

`infra/maint/opsctl_authz.json` maps subcommand names to a list of
allowed operator key fingerprints (SHA-256 hex of the 32-byte key):

```json
{
  "ops.maint-pause":   ["<fingerprint-A>", "<fingerprint-B>"],
  "ops.maint-resume":  ["<fingerprint-A>", "<fingerprint-B>"],
  "ops.restore":       ["<fingerprint-A>"],
  "ops.denylist-add":  ["<fingerprint-A>", "<fingerprint-B>"],
  "ops.denylist-clear":["<fingerprint-A>"]
}
```

> `ops.restore` is intentionally restricted to fewer keys — follow the
> principle of least privilege.

### 4.2 Compute a key fingerprint

```bash
python3 -c "
import hashlib, pathlib
key = pathlib.Path('infra/maint/opsctl_key.bin').read_bytes()
print(hashlib.sha256(key).hexdigest())
"
```

Paste the output into `infra/maint/opsctl_authz.json` for the relevant
subcommands.

### 4.3 Authz violation alerts

When a consumer receives an envelope whose key fingerprint is not in the
authz file for the requested subcommand it:

1. Rejects the envelope (does not process the command).
2. Emits `sec.alert.v1{kind=opsctl_unauthorized, severity=critical}`.
3. Increments `opsctl_rejected_total` counter.
4. Does **not** publish a `maint.ack.v1` for the rejected envelope.

---

## 5. Config knobs summary

| Knob | Default | Purpose |
|---|---|---|
| `OPSCTL_REQUIRE_SIGNATURE` | `true` | Consumer-side: reject envelopes without a valid HMAC signature. Set `false` only in dev/test environments. |
| `OPSCTL_KEY_FILE` | `infra/maint/opsctl_key.bin` | Path to the 32-byte binary operator key. |
| `OPSCTL_SPOOL_FLUSH_MAX_PER_RUN` | `100` | Max envelopes to re-publish in a single `ops.spool-flush` run. |

---

## 6. Cross-references

* **Exit codes:** [`xops/opsctl/_exit_codes.py`](../../xops/opsctl/_exit_codes.py) — `OPSCTL_KEY_REVOKED=9`, `SPOOL_FLUSH_ALREADY_RUNNING=8`.
* **Alert kinds:** `opsctl_signature_invalid`, `opsctl_unauthorized` in `KNOWN_SEC_ALERT_KINDS` ([`ai/swarm/agents/payloads.py`](../../ai/swarm/agents/payloads.py)).
* **Spool-flush lock:** [`docs/guides/backup_runbook.md`](backup_runbook.md) §5; `data/maint/opsctl_spool/.flush.lock`.
* **Chaos stubs:** `P12-8-W` (`chaos-opsctl-signature-forged`) in [`docs/testing/phase12_catalogue.md`](../testing/phase12_catalogue.md).
* **Consumer code:** [`xops/opsctl/_sign.py`](../../xops/opsctl/_sign.py) (signing), consumer verify in `ai/swarm/agents/maint/` (auth gate).

---

## 7. Key lifecycle (§8.15.4)

### 7.1 Key revocation

1. Revoke a key with `make ops.revoke-key OPERATOR=<email>` (adds the key
   fingerprint to the `revoked_keys` list in `opsctl_operators.json`).
2. The consumer applies a grace window of `cfg.opsctl_key_revocation_grace_s`
   (default 3600 s) from the revocation timestamp.  Envelopes signed by the
   revoked key are **accepted** during the grace period (facilitates
   zero-downtime key rotation) but are logged with `accepted=true, grace=true`.
3. After the grace window expires the consumer rejects the envelope with
   `accepted=false, reason=key_revoked` and returns exit code
   `9` (`OPSCTL_KEY_REVOKED`) to the caller.
4. A rejected-in-grace-period event emits
   `sec.alert.v1{kind=opsctl_signature_invalid, severity=critical}` and the
   caller receives a non-zero exit to trigger alerting.

### 7.2 Key rotation

1. Generate a new Ed25519 key pair: `make ops.rotate-key OPERATOR=<email>`.
2. Add the new public key to `opsctl_operators.json`; leave the old key active
   until the grace period expires (`cfg.opsctl_key_revocation_grace_s`).
3. Keys with age > `cfg.opsctl_key_max_age_days` (default 365 d) emit
   `sec.alert.v1{kind=opsctl_key_rotation_overdue, severity=warn}` once per
   day per key until rotated.
4. After the new key is confirmed operational, revoke the old key (§7.1).

### 7.3 Kill-switch

* `make ops.kill-switch-status` checks `cfg.opsctl_kill_switch_max_age_h`
  (default 24 h).  If the kill-switch file is older than the threshold the
  consumer enters fail-safe (all ops rejected) until the file is refreshed.
* Refresh via `make ops.kill-switch-refresh`.

### 7.4 Rate limiting

* Per-key token bucket at `cfg.opsctl_key_rate_limit_per_min` (default 30
  tokens/min).  Exhaustion emits
  `sec.alert.v1{kind=opsctl_key_rate_limited, severity=warn}` debounced 5 min
  per key.  Blast-radius cap for stolen keys.

### 7.5 Operators file reload

* The consumer re-reads `opsctl_operators.json` every
  `cfg.opsctl_operators_reload_s` (default 60 s).  A reload failure (file
  missing or parse error) emits
  `sec.alert.v1{kind=opsctl_operators_unreadable, severity=critical}` and the
  consumer enters fail-safe (all signatures rejected until the file is repaired).

### 7.6 Updated cross-references

* **New alert kinds (§8.15.4):** `opsctl_key_rotation_overdue`,
  `opsctl_operators_unreadable`, `opsctl_key_rate_limited` — added to
  `KNOWN_SEC_ALERT_KINDS` in
  [`ai/swarm/agents/payloads.py`](../../ai/swarm/agents/payloads.py).
* **Per-kind schema stubs:** `ai/swarm/sdk/schemas/sec.alert.v1/` — one JSON
  stub per new kind.
* **Chaos coverage:** `P12-8-Z` (`chaos-revoked-key-replay`) in
  [`docs/testing/phase12_catalogue.md`](../testing/phase12_catalogue.md).

---

## 8. key_id derivation and self-verification (§8.16.14)

### 8.1 Why key_id exists

`opsctl_operators.json` maps `key_id → {email, added_at, revoked_at}`.
The `key_id` lets consumers validate an envelope's provenance without
ever reading the operator's private key. Two operators reviewing each
other's PRs can **mechanically confirm** the mapping is correct — no
Slack screenshots or trust-based review.

### 8.2 Canonical derivation

```
key_id = sha256(f"negelir-opsctl-key-v1|{operator_email}|{base64(key_bytes)}")[:16]
```

(Result is a 16-character lowercase hex string.)

Three invariants this derivation provides:

1. **Email binding** — a key holder cannot impersonate another operator
   by re-using their `key_id`.  Changing the email in the derivation
   input changes the `key_id`.
2. **Key-bytes binding** — collision attacks require finding two keys
   with the same 64-bit SHA truncation for the same email. Infeasible
   in practice.
3. **Domain separator** (`negelir-opsctl-key-v1`) — future derivation
   schemes roll forward (e.g. `-v2`) without colliding with v1 ids.

The single implementation is `xops/maint/key_id.py::derive(email, key_bytes) -> str`.
An AST scan asserts this is the **only** place in the codebase that
derives a `key_id`; ad-hoc derivations fail CI.

### 8.3 Bootstrapping a new operator key

`make ops.bootstrap-key` generates 32 cryptographically random bytes,
writes them to `~/.negelir/opsctl_key` (mode 0600), computes the
canonical `key_id`, and prints the line the operator copies into their
PR:

```json
"<key_id>": {"email": "<operator-email>", "added_at": "<iso>", "revoked_at": null}
```

Steps:

1. Run `make ops.bootstrap-key` on the operator's workstation.
2. Copy the printed JSON line into `infra/maint/opsctl_operators.json`.
3. Open a PR.  A second reviewer runs `make ops.verify-key-id OPERATOR=<email>`
   on a machine where they have imported the operator's **public key**
   (not the private bytes) — the verify command computes the expected
   `key_id` from the public material and asserts it matches the operators
   file.

### 8.4 Self-verification after pulling main

After a `make git` (or equivalent) that touched `opsctl_operators.json`,
each operator should confirm their own entry is intact:

```bash
make ops.verify-key-id OPERATOR=<your-email>
```

The command:
1. Reads the local key at `~/.negelir/opsctl_key` (or `OPSCTL_KEY_FILE`).
2. Computes `key_id` via `xops/maint/key_id.py::derive`.
3. Looks up the entry for `<your-email>` in `infra/maint/opsctl_operators.json`.
4. Asserts the derived `key_id` matches the stored one.

On success: exits 0, prints `key_id OK: <key_id>`.
On mismatch: exits with `key_id_drift` (see §8.5 below).

### 8.5 `key_id_drift` — diagnosis and recovery

`key_id_drift` means the locally derived `key_id` does not match
`opsctl_operators.json`.  Causes:

| Cause | Diagnosis | Fix |
|---|---|---|
| Operators file updated in a merge without regenerating the local key | Derived `key_id` != stored `key_id` for your email | Re-run `make ops.bootstrap-key`, update operators file, reopen PR. |
| Wrong email passed to `make ops.verify-key-id` | Lookup fails or finds a different entry | Re-run with your exact email (case-sensitive). |
| Local key file corrupted or replaced | `key_id` derived from wrong bytes | Re-generate the key; update operators file. Treat old key as revoked (§7.1). |
| Entry manually edited in operators file | Stored `key_id` does not match the key bytes | Restore the entry from the correct derivation output. |

The `key_id_drift` alert also fires on the `sec.alert.v1` bus when the
**consumer** detects that an incoming envelope's signer key yields a
different `key_id` than the one recorded for that operator in the active
operators file (e.g. after a key rotation where the operators file was
not yet updated).

### 8.6 Config knobs

| Knob | Default | Purpose |
|---|---|---|
| `OPSCTL_KEY_FILE` | `infra/maint/opsctl_key.bin` | Path to the 32-byte binary operator key (host) or `~/.negelir/opsctl_key` (workstation). |
| `OPSCTL_OPERATORS_FILE` | `infra/maint/opsctl_operators.json` | Operators registry read by consumers and by `make ops.verify-key-id`. |

### 8.7 Cross-references

* **Derivation function:** [`xops/maint/key_id.py`](../../xops/maint/key_id.py).
* **CLI commands:** `make ops.bootstrap-key`, `make ops.verify-key-id OPERATOR=<email>`.
* **Alert kind:** `key_id_drift` in `KNOWN_SEC_ALERT_KINDS`
  ([`ai/swarm/agents/payloads.py`](../../ai/swarm/agents/payloads.py)).
* **AST scan:** boundary test asserts `key_id.py::derive` is the single
  derivation site.
* **Chaos coverage:** `P12-8-AF` (TBD) in
  [`docs/testing/phase12_catalogue.md`](../testing/phase12_catalogue.md).

