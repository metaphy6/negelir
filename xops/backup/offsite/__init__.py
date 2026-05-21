"""ROADMAP §8.12 — off-host backup replication target package.

Exposes:
* :class:`~xops.backup.offsite.targets.OffsiteBackupTarget` — the Protocol
* :class:`~xops.backup.offsite.targets.S3CompatibleTarget`
* :class:`~xops.backup.offsite.targets.RsyncSshTarget`
* :class:`~xops.backup.offsite.targets.NoopTarget`
* :class:`~xops.backup.offsite.targets.BackupOffsiteConfigError`
* :func:`~xops.backup.offsite.targets.target_from_cfg` — factory
* :func:`~xops.backup.offsite.integrity.upload_with_integrity` — §8.12
* :func:`~xops.backup.offsite.integrity.build_manifest` — §8.12
* :class:`~xops.backup.offsite.integrity.ObjectIntegrityError` — §8.12
* :func:`~xops.backup.offsite.retention.prune_offsite_objects` — §8.12
* :class:`~xops.backup.offsite.retention.OffsiteRetentionResult` — §8.12
"""

from xops.backup.offsite.integrity import (
    ObjectIntegrityError,
    build_manifest,
    upload_with_integrity,
)
from xops.backup.offsite.retention import (
    OffsiteRetentionResult,
    prune_offsite_objects,
)
from xops.backup.offsite.targets import (
    BackupOffsiteConfigError,
    NoopTarget,
    OffsiteBackupTarget,
    RsyncSshTarget,
    S3CompatibleTarget,
    target_from_cfg,
)

__all__ = [
    "BackupOffsiteConfigError",
    "NoopTarget",
    "ObjectIntegrityError",
    "OffsiteBackupTarget",
    "OffsiteRetentionResult",
    "RsyncSshTarget",
    "S3CompatibleTarget",
    "build_manifest",
    "prune_offsite_objects",
    "target_from_cfg",
    "upload_with_integrity",
]
