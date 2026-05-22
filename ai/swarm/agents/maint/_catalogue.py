"""Phase 8 §8.15.6 — Maint-plane deployment catalogue (machine-readable).

Single source of truth for K8s + compose deployment data for every
§8.x maint-plane agent.  Phase 14 manifests must match every cell;
the boundary test ``test_phase8_15_6_catalogue.py`` asserts compose
columns today.  K8s columns marked ``PENDING_PHASE_14`` are reserved
for the Phase 14 manifest author and are NOT yet asserted by CI.

Cross-phase agents (``consensus.v1``, ``sec.rate.v1``, ``trainer.v1``)
are listed here because they appear in ``cfg.opsctl_critical_agents``
or ``cfg.maint_scaler_self_scaling_targets``; the boundary test asserts
they have rows.  Their full deployment docs live in the phase that owns
them; only the maint-plane view is captured here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Sentinel: K8s column not yet decided – filled by Phase 14 manifest author.
PENDING_PHASE_14 = "pending Phase 14"


@dataclass(frozen=True)
class AgentCatalogueRow:
    """One row per deployable unit in the maint plane."""

    # ── Identity ─────────────────────────────────────────────────────────────
    agent_id: str
    """Stable v1 agent identifier (e.g. ``maint.backup.v1``)."""

    roadmap_section: str
    """Primary ROADMAP section that defines this agent (e.g. ``§8.3``)."""

    # ── K8s columns (authoritative for Phase 14 manifests) ───────────────────
    k8s_namespace: str
    service_account: str
    rbac_rules: List[str] = field(default_factory=list)
    secrets_referenced: List[str] = field(default_factory=list)
    pvcs_mounted: List[str] = field(default_factory=list)
    pg_role: Optional[str] = None
    redis_acl_user: Optional[str] = None
    lease_name: Optional[str] = None
    network_egress: str = "intra-cluster only"

    # ── Compose / dev columns (authoritative today) ───────────────────────────
    compose_service_name: str = ""
    """Docker Compose service name, or ``N/A`` for operator CLI tools."""

    compose_volumes: List[str] = field(default_factory=list)
    host_paths: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalogue — ordered by ROADMAP section
# ---------------------------------------------------------------------------
CATALOGUE: List[AgentCatalogueRow] = [
    # ── §8.2 Auto-scaler ────────────────────────────────────────────────────
    AgentCatalogueRow(
        agent_id="maint.scaler.v1",
        roadmap_section="§8.2",
        k8s_namespace="negelir-maint",
        service_account="maint-scaler",
        rbac_rules=[
            "patch apps/v1.Deployment/scale (negelir-maint)",
            "get list watch apps/v1.Deployment (negelir-maint)",
            "get create update coordination.k8s.io/v1.Lease (negelir-maint)",
        ],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name="maint.scaler.v1",
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/maint/"],
    ),
    # ── §8.3 Backup / retention ─────────────────────────────────────────────
    AgentCatalogueRow(
        agent_id="maint.backup.v1",
        roadmap_section="§8.3",
        k8s_namespace="negelir-maint",
        service_account="maint-backup",
        rbac_rules=[
            "get create update coordination.k8s.io/v1.Lease (negelir-maint)",
            "create get list watch delete batch/v1.Job (negelir-maint-verify)",
            "delete persistentvolumeclaims (negelir-maint-verify)",
            "get secrets/negelir-backup-verify-key (negelir-maint-verify)",
        ],
        secrets_referenced=[
            "negelir-backup-verify-key (negelir-maint-verify; ephemeral "
            "per-dump, rotated by agent when "
            "cfg.maint_backup_verify_key_rotate_per_dump=true)",
        ],
        pvcs_mounted=[
            "maint-backup-pvc (cfg.maint_backup_dir, RWO, "
            ">=cfg.maint_backup_pvc_size_gb)",
            "maint-verify-pvc (negelir-maint-verify, ephemeral per-dump RWO, "
            "emptyDir.sizeLimit=2x_last_dump_size — SidecarVerifier Job, "
            "deleted after verify)",
        ],
        pg_role="negelir_backup",
        redis_acl_user=None,
        lease_name="maint.backup.v1",
        network_egress=(
            "intra-cluster + outbound S3-compatible "
            "(cfg.maint_backup_offsite_endpoint)"
        ),
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/backups/", "data/maint/"],
    ),
    # ── §8.5 DLQ supervisor ─────────────────────────────────────────────────
    AgentCatalogueRow(
        agent_id="maint.dlq.v1",
        roadmap_section="§8.5",
        k8s_namespace="negelir-maint",
        service_account="maint-dlq",
        rbac_rules=[
            "get create update coordination.k8s.io/v1.Lease (negelir-maint)",
        ],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name="maint.dlq.v1",
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/maint/"],
    ),
    # ── §8.6 Schema-drift sentinel ──────────────────────────────────────────
    AgentCatalogueRow(
        agent_id="maint.schema.v1",
        roadmap_section="§8.6",
        k8s_namespace="negelir-maint",
        service_account="maint-schema",
        rbac_rules=[
            "get create update coordination.k8s.io/v1.Lease (negelir-maint)",
        ],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name="maint.schema.v1",
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/maint/"],
    ),
    # ── §8.7 + §8.8 Sec-allowlist / decimate agent ──────────────────────────
    AgentCatalogueRow(
        agent_id="maint.sec.v1",
        roadmap_section="§8.7 + §8.8",
        k8s_namespace="negelir-maint",
        service_account="maint-sec",
        rbac_rules=[
            "get create update coordination.k8s.io/v1.Lease (negelir-maint)",
        ],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name="maint.sec.v1",
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/maint/"],
    ),
    # ── §8.14.4 opsctl (operator CLI) ───────────────────────────────────────
    # Not an agent; runs as an operator CLI / short-lived K8s Job in Phase 14.
    AgentCatalogueRow(
        agent_id="opsctl",
        roadmap_section="§8.14.4",
        k8s_namespace=PENDING_PHASE_14,  # short-lived Job in negelir-maint
        service_account=PENDING_PHASE_14,
        rbac_rules=[],  # application-layer authz via HMAC — no K8s RBAC
        secrets_referenced=[
            "negelir-opsctl-operators (opsctl operators' HMAC key bundle, "
            "infra/maint/opsctl_operators.json — read at boot)",
        ],
        pvcs_mounted=[
            "opsctl-spool-pvc (data/maint/opsctl_spool/, RWX — shared if "
            "multiple operator pods in Phase 14)",
        ],
        pg_role=None,
        redis_acl_user="negelir_opsctl",
        lease_name=None,
        network_egress="Redis publish only (maint.event.v1 stream)",
        compose_service_name="N/A",  # operator CLI; invoked via `make ops.*`
        compose_volumes=["./data:/data (mounted in ai service for spool dir)"],
        host_paths=["data/maint/opsctl_spool/", "data/maint/opsctl_audit.csv"],
    ),
    # ── Cross-phase agents referenced by maint-plane config ─────────────────
    # Listed because they appear in cfg.opsctl_critical_agents or
    # cfg.maint_scaler_self_scaling_targets.  Full deployment docs live
    # in the phase that owns them; only maint-plane relevance captured here.
    AgentCatalogueRow(
        agent_id="consensus.v1",
        roadmap_section="§3 (Phase 3)",
        k8s_namespace=PENDING_PHASE_14,
        service_account=PENDING_PHASE_14,
        rbac_rules=[],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name=None,
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/maint/"],
    ),
    AgentCatalogueRow(
        agent_id="sec.rate.v1",
        roadmap_section="§7 (Phase 7)",
        k8s_namespace=PENDING_PHASE_14,
        service_account=PENDING_PHASE_14,
        rbac_rules=[],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name=None,
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/maint/"],
    ),
    AgentCatalogueRow(
        agent_id="trainer.v1",
        roadmap_section="§5 (Phase 5)",
        k8s_namespace=PENDING_PHASE_14,
        service_account=PENDING_PHASE_14,
        rbac_rules=[],
        secrets_referenced=[],
        pvcs_mounted=[],
        pg_role=None,
        redis_acl_user=None,
        lease_name=None,
        network_egress="intra-cluster only",
        compose_service_name="ai",
        compose_volumes=["./data:/data"],
        host_paths=["data/models/", "data/maint/"],
    ),
]

# Indexed by agent_id for O(1) lookup in tests.
CATALOGUE_BY_AGENT_ID: Dict[str, AgentCatalogueRow] = {
    row.agent_id: row for row in CATALOGUE
}
