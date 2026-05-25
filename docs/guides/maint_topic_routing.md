# Maint Topic Routing Guide

> **Phase 8 §8.16.9** operator-facing doctrine for `maint.event.v1`
> and `sec.alert.v1` crossover routing.

---

## 1. Why this guide exists

Maintenance-plane operators need a deterministic answer to one recurring
question: "does this signal go to the audit topic, the paging topic, or both?"

The producer-side source of truth is the static lookup in
`ai/swarm/sdk/_dual_emit_helper.py` (`_KIND_TOPIC_TABLE`). This guide mirrors
that table in a human-readable form and explains how to join dual-emitted
signals.

## 2. Topic roles (doctrine)

| Topic | Role | Operator meaning |
|---|---|---|
| `maint.event.v1` | Audit trail | Complete timeline of maint-plane actions, including successful no-ops. |
| `sec.alert.v1` | Paging / security | Only events requiring attention now (or explicit security signals). |

When a kind appears on both topics, treat `maint.event.v1` as the canonical
timeline row and `sec.alert.v1` as the paging mirror.

## 3. Routing table (current source-of-truth mirror)

| Kind | Emit to `maint.event.v1` | Emit to `sec.alert.v1` | Notes |
|---|---|---|---|
| `backup_completed` | Yes | No | Routine success; audit-only. |
| `backup_verify_failed` | Yes | Yes | Audit + page. Join via the same `event_correlation_id`. |
| `opsctl_signature_invalid` | No | Yes | Security signal; page-only. |

If a new `kind` is introduced and not added to the routing table, producers
fail fast with a boundary error; this is intentional.

## 4. `event_correlation_id` join pattern

For dual-emitted kinds, both topic envelopes carry the same
`event_correlation_id` value so operators can join them into one incident
thread.

Derivation rule:

```text
event_correlation_id = sha256(f"{kind}|{target}|{produced_at}")[:16]
```

Operator workflow:

1. Read the paging row on `sec.alert.v1`.
2. Copy `event_correlation_id`.
3. Query `maint.event.v1` for the same id to retrieve the audit context.
4. Use `request_id` and `produced_at` from the audit row as the incident anchor.

## 5. Operational checks

Before relying on routing in production:

1. Run `ai/swarm/sdk/tests/test_phase8_16_9_dual_emit_helper.py` to confirm
   expected routing and missing-row fail-fast behavior.
2. Verify producer factories are still wired through the shared helper:
   `MaintEvent.publish_topics(...)` and `SecAlert.publish_topics(...)`.
