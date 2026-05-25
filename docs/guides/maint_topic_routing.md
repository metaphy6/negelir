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

The canonical source is `ai/swarm/sdk/_dual_emit_helper.py::_KIND_TOPIC_TABLE`.
This table mirrors it for human readability. Entries marked **dual-emit** carry
`event_correlation_id` on both envelopes.

### 3.1 Existing kinds (pre-§8.16)

| Kind | `maint.event.v1` | `sec.alert.v1` | Dual-emit | Notes |
|---|---|---|---|---|
| `backup_completed` | ✓ | — | No | Routine success; audit-only. |
| `backup_verify_failed` | ✓ | ✓ | **Yes** | Audit + page. Join via `event_correlation_id`. |
| `opsctl_signature_invalid` | — | ✓ | No | Security signal; page-only. |

### 3.2 New kinds added in §8.16.16

**Maint-audit-only (emit to `maint.event.v1` only):**

| Kind | Notes |
|---|---|
| `maint_scaler_default_applied` | Scaler applied global default config because no per-agent entry was found. |
| `spool_flush_acks_reconciled` | Spool flush ack reconciliation round completed. |
| `prune_started` | Prune operation initiated (at least one row eligible). |
| `prune_completed` | Prune operation finished normally. |
| `prune_skipped` | Prune run found zero eligible rows; recorded as a no-op audit row. |
| `backup_offsite_upload_id_expired` | S3/GCS/B2 multipart upload-id was aborted by bucket lifecycle; agent restarted upload from scratch. Fields: `dump_date`, `original_upload_id`, `age_h`. |
| `dlq_replay_policy_loaded` | DLQ replay policy loaded at boot. Fields: `deny_prefixes`, `deny_suffixes`, `allow_overrides`. Enables policy audits from the bus timeline. |
| `pattern_allowlist_legacy_hit` | Allowlist row matched via legacy plain-SHA fingerprint (`fingerprint_alg='s'`). Debounced per row. Prompts operator to run `make ops.allowlist-rehash`. |
| `backup_model_lineage_legacy` | Pre-§8.16 model artifact found without a lineage sidecar. Info-level; operator backfills via `make ops.retrain-for-lineage`. |

**Security/paging-only (emit to `sec.alert.v1` only):**

| Kind | Severity | Notes |
|---|---|---|
| `maint_scaler_unconfigured_agent` | warn | Agent running without a replica-config entry in the scaler registry. |
| `maint_scaler_orphan_cfg` | warn | Replica-config entry exists for an agent not seen in any recent heartbeat. |
| `spool_flush_acks_incomplete` | warn | Spool flush completed but one or more envelopes did not receive an ack within the window. |
| `backup_offsite_lifecycle_too_aggressive` | warn | Bucket's `AbortIncompleteMultipartUpload.DaysAfterInitiation` < `cfg.maint_backup_offsite_lifecycle_min_days`. Debounced daily. |
| `backup_offsite_preflight_failed` | critical | Object-Lock preflight probe failed (see §8.16.6 + `docs/guides/backup_runbook.md §7.2`). Agent enters spool-mode until probe recovers. |
| `vram_footprint_unknown` | info | Agent has not emitted `model_registered`; scaler falls back to global default. Scale-up refused when GPU capacity is tight. |
| `allowlist_hmac_key_rotation_overdue` | warn | HMAC key age exceeds `cfg.sec_input_allowlist_hmac_key_max_age_days`. Emitted daily until rotated. |
| `sec_plane_lag_high` | warn/critical | `sec.alert.v1` consumer lag exceeded the §8.16.11 symmetric watchdog threshold. |
| `key_id_drift` | critical | Local operator key's derived `key_id` does not match the entry in `opsctl_operators.json`. Run `make ops.verify-key-id`. |
| `fail_safe_lineage_writer_missing` | critical | `swarm` chart version is below the lineage-writer floor required by `RegistryAuditor`. Boot refusal. |

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
