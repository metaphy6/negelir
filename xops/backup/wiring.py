"""Phase 8 §8.3 — backup driver wiring factory.

Bridges :mod:`ai.common.config` to the live
:class:`xops.backup.executors.LocalPgDumpExecutor` /
:class:`xops.backup.verifier.LocalSubprocessVerifier` adapters.

Used by the swarm bootstrap so the
:class:`swarm.agents.maint.backup.MaintBackupAgent` is
constructed with the correct adapters per profile:

* **Production profile** (``cfg.maint_backup_pg_dsn`` set): live
  drivers, ``verify_backup_role`` runs at boot, refuse-to-start on
  any cfg gap.
* **Dev / CI profile** (DSN empty): in-memory shims (the agent's
  default constructor) so tests do not need a live Postgres.

Pure-stdlib, DI-friendly. The bootstrap calls
:func:`build_backup_drivers(cfg)` once at startup; the result is
passed straight into ``MaintBackupAgent(...)``.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from xops.backup.executors import LocalPgDumpExecutor, LocalPgPruner
from xops.backup.role_probe import BackupRoleError, verify_backup_role
from xops.backup.verifier import LocalSubprocessVerifier

if TYPE_CHECKING:  # pragma: no cover
    from ai.common.config import Config


_log = logging.getLogger("xops.backup.wiring")


@dataclass(frozen=True)
class BackupDrivers:
    """Bundle returned by :func:`build_backup_drivers`.

    ``dump`` and ``verifier`` may be ``None`` when the cfg profile
    has not enabled the live drivers — the caller is expected to
    pass ``None`` straight through to ``MaintBackupAgent`` so the
    in-memory shims are used.
    """

    dump: Optional[LocalPgDumpExecutor]
    verifier: Optional[LocalSubprocessVerifier]
    pruner: Optional[LocalPgPruner]
    profile: str  # "live" | "shim"


class BackupWiringError(RuntimeError):
    """Refuse-to-start: cfg profile is incomplete or inconsistent."""


def build_backup_drivers(cfg: "Config") -> BackupDrivers:
    """Construct the live backup drivers from cfg, or return shims.

    Resolution rules (binding):

    1. If ``cfg.maint_backup_pg_dsn`` is empty → ``profile=shim``,
       both fields are ``None``. Tests + dev runtime use this path.
    2. If DSN is set, ``cfg.maint_backup_age_recipients_file`` AND
       ``cfg.maint_backup_age_identity_file`` MUST also be set,
       both must exist on disk, and the boot probe
       ``verify_backup_role`` must succeed. Any failure raises
       :class:`BackupWiringError` — the swarm bootstrap treats
       this as fatal.
    """
    dsn = (cfg.maint_backup_pg_dsn or "").strip()
    if not dsn:
        _log.info("build_backup_drivers profile=shim (no pg_dsn)")
        return BackupDrivers(dump=None, verifier=None, pruner=None, profile="shim")

    # ROADMAP §8.3 restore-verify mechanism is runtime-aware.
    # `LocalSubprocessVerifier` is compose/host only; `k8s`
    # requires the SidecarVerifier adapter that lands in Phase 14.
    runtime = str(getattr(cfg, "maint_runtime", "none") or "none").strip()
    if runtime == "k8s":
        raise BackupWiringError(
            "maint_runtime='k8s' requires SidecarVerifier (Phase 14); "
            "LocalSubprocessVerifier is compose-only"
        )

    recipients = (cfg.maint_backup_age_recipients_file or "").strip()
    identity = (cfg.maint_backup_age_identity_file or "").strip()
    image = (cfg.maint_backup_verify_pg_image or "").strip()
    if not recipients or not os.path.isfile(recipients):
        raise BackupWiringError(
            f"maint_backup_age_recipients_file={recipients!r} missing or unreadable; "
            f"refuse-to-start instead of writing plaintext dumps"
        )
    if not identity or not os.path.isfile(identity):
        raise BackupWiringError(
            f"maint_backup_age_identity_file={identity!r} missing or unreadable; "
            f"refuse-to-start instead of producing un-verifiable dumps"
        )
    if not image:
        raise BackupWiringError(
            "maint_backup_verify_pg_image is empty; refuse-to-start"
        )
    if image.endswith(":latest") or image.endswith("-latest"):
        raise BackupWiringError(
            f"maint_backup_verify_pg_image={image!r} must pin a specific tag "
            f"(no *-latest)"
        )

    # Probe DB identity AND role-connection limit headroom.
    try:
        verify_backup_role(
            pg_dsn=dsn,
            pg_jobs=int(cfg.maint_backup_pg_jobs),
        )
    except BackupRoleError as exc:
        raise BackupWiringError(str(exc)) from exc

    dump = LocalPgDumpExecutor(
        backup_dir=cfg.maint_backup_dir,
        pg_dsn=dsn,
        pg_jobs=int(cfg.maint_backup_pg_jobs),
        age_recipients_file=recipients,
        nice_level=int(cfg.maint_backup_pg_dump_nice_level),
        ionice_enabled=bool(cfg.maint_backup_pg_dump_ionice),
    )
    verifier = LocalSubprocessVerifier(
        backup_dir=cfg.maint_backup_dir,
        pg_image=image,
        age_identity_file=identity,
        pg_jobs=int(cfg.maint_backup_pg_jobs),
        max_version_gap=int(cfg.maint_backup_max_version_gap),
    )
    pruner = LocalPgPruner(
        pg_dsn=dsn,
        prune_batch=int(cfg.maint_backup_prune_batch),
        sec_quarantine_ttl_days=int(cfg.sec_quarantine_ttl_days),
        schema_snapshot_retention_days=int(cfg.maint_schema_snapshot_retention_days),
        dlq_retention_days=int(cfg.swarm_dlq_pg_retention_days),
        audit_retention_days=int(cfg.maint_audit_retention_days),
    )
    _log.info(
        "build_backup_drivers profile=live dir=%s pg_jobs=%d image=%s",
        cfg.maint_backup_dir, cfg.maint_backup_pg_jobs, image,
    )
    return BackupDrivers(dump=dump, verifier=verifier, pruner=pruner, profile="live")


__all__ = [
    "BackupDrivers",
    "BackupWiringError",
    "build_backup_drivers",
]
