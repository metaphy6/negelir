# Security Exceptions

> **Phase 8 §8.16.7** — operator-audited registry for sensitive replay
> exceptions and other narrowly-scoped security carve-outs.
>
> **Audience:** operators and security reviewers who need to authorize
> a topic for DLQ replay that would otherwise be denied by the layered
> `DENY_PREFIXES` / `DENY_SUFFIXES` ruleset in
> `ai/swarm/agents/maint/dlq/replay_policy.py`.

---

## 1. Purpose

The DLQ replay-policy module (`replay_policy.py`) applies a layered
deny ruleset before allowing any re-replay of a dead-letter envelope.
Prefixes such as `auth.`, `payment.`, `sec.`, `maint.`, and `patcher.`
are permanently denied to prevent credential, PCI-scope, or
control-plane data from re-entering the processing pipeline.

In rare cases a team may need to replay a topic that falls under a
normally-denied prefix (example: a custom `sec.audit.v1` topic where
payloads carry NO credentials and a one-time forensic replay is
required). Such overrides are **never automatic** — each must be:

1. Documented in this file with a justification and sign-off.
2. Added to `NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES` in
   `xops/env/.env` (one topic per line).
3. Backed by a Phase 12 chaos-catalogue stub verifying the replay
   path is safe (referenced in the `phase12_stub` column below).

The CI gate `make verify.dlq-replay-policy` walks the
`ALLOW_OVERRIDES` list against this file and fails on orphans
(a topic in config that lacks a doc row, or vice-versa).

---

## 2. Override entry fields

Each row in the override table must carry:

| Field | Description |
|---|---|
| `topic` | Exact topic name (e.g. `sec.audit.v1.dlq`). Must match the value in `NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES`. This is the CI-gate lookup key. |
| `reason` | Concrete technical reason the topic requires override. Must explain why payload contains no credentials, PII, or PCI-scoped data. |
| `responsible_agent` | The agent id that produces / consumes this topic (`responsible_agent` in the override entry; maps to `agent_id` in the audit event). |
| `phase12_stub` | Chaos-catalogue stub ID from `docs/testing/phase12_catalogue.md` that exercises the replay path (proves the replay is safe). |
| `sign_off` | Handle of the operator who added the entry and authorized the exception (format: `@<handle> YYYY-MM-DD`). |

Additional fields tracked in the boot-time audit event
`maint.event.v1{kind=dlq_replay_policy_loaded}`:

| Field | Description |
|---|---|
| `override_id` | Derived as `sha256(topic)[:8]` — uniquely identifies the override entry in audit logs without repeating the full topic string. |
| `authorized_by` | Operator email extracted from the `sign_off` column handle via `opsctl_operators.json`. |
| `expires_at` | ISO-8601 UTC date after which the CI gate treats the override as expired (add as a fifth pipe-separated value in `sign_off` if a time-bound override is needed; `null` for permanent). |

---

## 3. Override table

Every topic listed here must also appear in
`NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES`.
CI verifies parity with `make verify.dlq-replay-policy`.

| topic | reason | responsible_agent | phase12_stub | sign_off |
| --- | --- | --- | --- | --- |

*(No overrides active. Add one row per override before enabling it.)*

---

## 4. How to add an override

1. Determine that the payload truly carries no credentials, PCI-scope
   data, or PII that would be dangerous to replay.
2. Add a Phase 12 chaos stub in `docs/testing/phase12_catalogue.md`
   that exercises the replay path (stub id format: `P12-8-<letter>`).
3. Add one row to the table above.
4. Add the topic to `NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES` in
   `xops/env/.env.example` AND your active `xops/env/.env`.
5. Run `make verify.dlq-replay-policy` — must pass (no orphans).
6. Add a tracker row: `make track.add PHASE=8 STATUS=adapted NOTE="DLQ override added for <topic>"`.

---

## 5. How to remove an override

1. Delete the row from the table above.
2. Remove the topic from `NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES`
   in both `xops/env/.env.example` and `xops/env/.env`.
3. Run `make verify.dlq-replay-policy` — must pass.
4. Archive the Phase 12 stub (mark it `retired` in the catalogue) if
   no other path exercises it.

---

## 6. Cross-references

* **Replay policy module:** `ai/swarm/agents/maint/dlq/replay_policy.py`
  — `DENY_PREFIXES`, `DENY_SUFFIXES`, `ALLOW_OVERRIDES`, `is_replayable()`.
* **Audit kind:** `dlq_replay_policy_loaded` in `KNOWN_MAINT_EVENT_KINDS`
  ([`ai/swarm/agents/payloads.py`](../../ai/swarm/agents/payloads.py)).
* **CI gate:** `make verify.dlq-replay-policy`
  ([`xops/makefile/maint.py`](../../xops/makefile/maint.py)).
* **Config knob:** `NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES` in
  [`xops/env/.env.example`](../../xops/env/.env.example) and
  `ai/common/config.py` (`maint_dlq_replay_allow_overrides`).
* **Phase 12 catalogue:** [`docs/testing/phase12_catalogue.md`](../testing/phase12_catalogue.md).

