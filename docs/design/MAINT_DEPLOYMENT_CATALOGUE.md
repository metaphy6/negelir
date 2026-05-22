# Maint-Plane Deployment Catalogue

> **Status:** Phase 8 (pre-Phase-14 doc-only form).  
> **Source of truth:** This document is generated from
> `ai/swarm/agents/maint/_catalogue.py`.  Keep both in sync.  
> **CI gate:** `test_phase8_15_6_catalogue.py` asserts compose columns
> are valid today; K8s columns are validated when Phase 14 manifests land.

---

## Purpose

Single lookup table for every deployable unit in the maint plane.
Phase 14 manifest authors start here — every column maps to a
named resource in `infra/k8s/maint/`.

**Columns marked `pending Phase 14`** are reserved; CI does not yet
assert them.  All other columns (especially the compose columns) are
asserted by `test_phase8_15_6_catalogue.py`.

---

## Agent Catalogue

<!-- ───────────────── §8.2 Auto-scaler ──────────────────────────────── -->

### `maint.scaler.v1` (§8.2)

| Field | Value |
|---|---|
| **agent_id** | `maint.scaler.v1` |
| **roadmap_section** | §8.2 |
| **k8s_namespace** | `negelir-maint` |
| **service_account** | `maint-scaler` |
| **rbac_rules** | `patch apps/v1.Deployment/scale (negelir-maint)` · `get list watch apps/v1.Deployment (negelir-maint)` · `get create update coordination.k8s.io/v1.Lease (negelir-maint)` |
| **secrets_referenced** | — |
| **pvcs_mounted** | — |
| **pg_role** | — |
| **redis_acl_user** | — |
| **lease_name** | `maint.scaler.v1` |
| **network_egress** | intra-cluster only |
| **compose_service_name** | `ai` |
| **compose_volumes** | `./data:/data` |
| **host_paths** | `data/maint/` |

---

<!-- ───────────────── §8.3 Backup / retention ─────────────────────────── -->

### `maint.backup.v1` (§8.3)

| Field | Value |
|---|---|
| **agent_id** | `maint.backup.v1` |
| **roadmap_section** | §8.3 |
| **k8s_namespace** | `negelir-maint` |
| **service_account** | `maint-backup` |
| **rbac_rules** | `get create update coordination.k8s.io/v1.Lease (negelir-maint)` · `create get list watch delete batch/v1.Job (negelir-maint-verify)` · `delete persistentvolumeclaims (negelir-maint-verify)` · `get secrets/negelir-backup-verify-key (negelir-maint-verify)` |
| **secrets_referenced** | `negelir-backup-verify-key` (ns: `negelir-maint-verify`; ephemeral per-dump, rotated by agent when `cfg.maint_backup_verify_key_rotate_per_dump=true`) |
| **pvcs_mounted** | `maint-backup-pvc` (`cfg.maint_backup_dir`, RWO, ≥`cfg.maint_backup_pvc_size_gb`) · `maint-verify-pvc` (`negelir-maint-verify`, ephemeral per-dump RWO, `emptyDir.sizeLimit=2×last_dump_size` — SidecarVerifier Job, deleted after verify) |
| **pg_role** | `negelir_backup` (`pg_read_all_data` + `USAGE on pg_catalog`; migration `011_backup_role.sql`) |
| **redis_acl_user** | — |
| **lease_name** | `maint.backup.v1` |
| **network_egress** | intra-cluster + outbound S3-compatible (`cfg.maint_backup_offsite_endpoint`) |
| **compose_service_name** | `ai` |
| **compose_volumes** | `./data:/data` |
| **host_paths** | `data/backups/` · `data/maint/` |

---

<!-- ───────────────── §8.5 DLQ supervisor ───────────────────────────── -->

### `maint.dlq.v1` (§8.5)

| Field | Value |
|---|---|
| **agent_id** | `maint.dlq.v1` |
| **roadmap_section** | §8.5 |
| **k8s_namespace** | `negelir-maint` |
| **service_account** | `maint-dlq` |
| **rbac_rules** | `get create update coordination.k8s.io/v1.Lease (negelir-maint)` |
| **secrets_referenced** | — |
| **pvcs_mounted** | — |
| **pg_role** | — |
| **redis_acl_user** | — |
| **lease_name** | `maint.dlq.v1` |
| **network_egress** | intra-cluster only |
| **compose_service_name** | `ai` |
| **compose_volumes** | `./data:/data` |
| **host_paths** | `data/maint/` |

---

<!-- ───────────────── §8.6 Schema-drift sentinel ─────────────────────── -->

### `maint.schema.v1` (§8.6)

| Field | Value |
|---|---|
| **agent_id** | `maint.schema.v1` |
| **roadmap_section** | §8.6 |
| **k8s_namespace** | `negelir-maint` |
| **service_account** | `maint-schema` |
| **rbac_rules** | `get create update coordination.k8s.io/v1.Lease (negelir-maint)` |
| **secrets_referenced** | — |
| **pvcs_mounted** | — |
| **pg_role** | — |
| **redis_acl_user** | — |
| **lease_name** | `maint.schema.v1` |
| **network_egress** | intra-cluster only |
| **compose_service_name** | `ai` |
| **compose_volumes** | `./data:/data` |
| **host_paths** | `data/maint/` |

---

<!-- ───────────────── §8.7 + §8.8 Sec-allowlist / decimate ──────────── -->

### `maint.sec.v1` (§8.7 + §8.8)

| Field | Value |
|---|---|
| **agent_id** | `maint.sec.v1` |
| **roadmap_section** | §8.7 + §8.8 |
| **k8s_namespace** | `negelir-maint` |
| **service_account** | `maint-sec` |
| **rbac_rules** | `get create update coordination.k8s.io/v1.Lease (negelir-maint)` |
| **secrets_referenced** | — |
| **pvcs_mounted** | — |
| **pg_role** | — |
| **redis_acl_user** | — |
| **lease_name** | `maint.sec.v1` |
| **network_egress** | intra-cluster only |
| **compose_service_name** | `ai` |
| **compose_volumes** | `./data:/data` |
| **host_paths** | `data/maint/` |

---

<!-- ───────────────── §8.14.4 opsctl (operator CLI) ─────────────────── -->

### `opsctl` — operator CLI (§8.14.4)

> Not an agent; runs as an operator CLI on-host or as a short-lived
> K8s Job in Phase 14.

| Field | Value |
|---|---|
| **agent_id** | `opsctl` |
| **roadmap_section** | §8.14.4 |
| **k8s_namespace** | pending Phase 14 |
| **service_account** | pending Phase 14 |
| **rbac_rules** | — (application-layer authz via HMAC; no K8s RBAC needed) |
| **secrets_referenced** | `negelir-opsctl-operators` (opsctl HMAC key bundle, `infra/maint/opsctl_operators.json`) |
| **pvcs_mounted** | `opsctl-spool-pvc` (`data/maint/opsctl_spool/`, RWX — shared if multiple operator pods) |
| **pg_role** | — |
| **redis_acl_user** | `negelir_opsctl` (ACL: `+publish maint.event.v1 +subscribe maint.ack.v1 +client +ping`) |
| **lease_name** | — |
| **network_egress** | Redis publish only (`maint.event.v1` stream) |
| **compose_service_name** | N/A (operator CLI; invoked via `make ops.*`) |
| **compose_volumes** | `./data:/data` (mounted in `ai` service for spool dir) |
| **host_paths** | `data/maint/opsctl_spool/` · `data/maint/opsctl_audit.csv` |

---

## Cross-Phase Agents Referenced by Maint-Plane Config

The following agents appear in `cfg.opsctl_critical_agents` or
`cfg.maint_scaler_self_scaling_targets` and are therefore in scope
for the Phase 14 maint-namespace manifests.  Full deployment docs
live in the phase that owns each agent; this table covers only the
maint-plane view.

| agent_id | roadmap_section | compose_service_name | Notes |
|---|---|---|---|
| `consensus.v1` | §3 (Phase 3) | `ai` | In `cfg.opsctl_critical_agents` — opsctl monitors its ack latency |
| `sec.rate.v1` | §7 (Phase 7) | `ai` | In `cfg.opsctl_critical_agents` — opsctl can pause/resume it |
| `trainer.v1` | §5 (Phase 5) | `ai` | In `cfg.maint_scaler_self_scaling_targets` — scaler manages its replicas |

---

## K8s Resource Summary (for Phase 14 implementer)

| Resource type | Name | Namespace | Owner agent |
|---|---|---|---|
| Namespace | `negelir-maint` | — | all maint agents |
| Namespace | `negelir-maint-verify` | — | `maint.backup.v1` (SidecarVerifier Job) |
| ServiceAccount | `maint-scaler` | `negelir-maint` | `maint.scaler.v1` |
| ServiceAccount | `maint-backup` | `negelir-maint` | `maint.backup.v1` |
| ServiceAccount | `maint-dlq` | `negelir-maint` | `maint.dlq.v1` |
| ServiceAccount | `maint-schema` | `negelir-maint` | `maint.schema.v1` |
| ServiceAccount | `maint-sec` | `negelir-maint` | `maint.sec.v1` |
| Secret | `negelir-backup-verify-key` | `negelir-maint-verify` | `maint.backup.v1` |
| PVC | `maint-backup-pvc` | `negelir-maint` | `maint.backup.v1` |
| PVC | `maint-verify-pvc` | `negelir-maint-verify` | `maint.backup.v1` (ephemeral) |
| PVC | `opsctl-spool-pvc` | `negelir-maint` | `opsctl` |
| Lease | `maint.scaler.v1` | `negelir-maint` | `maint.scaler.v1` |
| Lease | `maint.backup.v1` | `negelir-maint` | `maint.backup.v1` |
| Lease | `maint.dlq.v1` | `negelir-maint` | `maint.dlq.v1` |
| Lease | `maint.schema.v1` | `negelir-maint` | `maint.schema.v1` |
| Lease | `maint.sec.v1` | `negelir-maint` | `maint.sec.v1` |
| PG Role | `negelir_backup` | — | `maint.backup.v1` (migration `011_backup_role.sql`) |
| PG Role | `negelir_audit_pruner` | — | `maint.backup.v1` prune path (migration `009_maint_audit.sql`) |
| Redis ACL | `negelir_opsctl` | — | `opsctl` (infra/redis/acl.conf) |

---

## Cross-References

- §8.2 `maint.scaler.v1` → see [ROADMAP §8.2](../planning/ROADMAP.md#82-auto-scaler-agent-maintscalerv1)
- §8.3 `maint.backup.v1` → see [ROADMAP §8.3](../planning/ROADMAP.md#83-backup--retention-agent-maintbackupv1)
- §8.5 `maint.dlq.v1` → see [ROADMAP §8.5](../planning/ROADMAP.md#85-dlq-supervisor-maintdlqv1)
- §8.6 `maint.schema.v1` → see [ROADMAP §8.6](../planning/ROADMAP.md#86-internal-schema-drift-sentinel-maintSchemav1)
- §8.10 Leader-election → see [ROADMAP §8.10](../planning/ROADMAP.md#810-liveness-leader-election-and-dead-mans-switch)
- §8.14.1 `negelir_audit_pruner` PG role → see [ROADMAP §8.14.1](../planning/ROADMAP.md#8141-maint_audit_log-range-partitioning-vacuum-bomb-fix)
- §8.14.4 `negelir_opsctl` Redis ACL → see [ROADMAP §8.14.4](../planning/ROADMAP.md#8144-opsctl-redis-acl--per-subcommand-authorization-signed-envelopes)
