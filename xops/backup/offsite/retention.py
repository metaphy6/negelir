"""ROADMAP §8.12 — offsite backup retention sweeper.

Prunes remote objects that are older than the configured retention window
(``cfg.maint_backup_offsite_retention_days``, default 90 d in prod / 7 d
in mock) independently of the on-host GFS-light retention.

Key constraint: Object Lock (WORM) prevents physical deletion until the
lock window has lapsed.  This module does *not* skip the ``delete()``
call for lock-active objects — the storage backend enforces the lock
silently (HTTP 403 -> no-op per :meth:`S3CompatibleTarget.delete`).
The result classifies each candidate as ``pruned`` (lock lapsed or absent)
or ``skipped_lock`` (lock still active) so the caller can record without
erroring.

Design constraints (binding):
* Pure-stdlib; no third-party deps.
* **No imports from** ``swarm.*``, ``psycopg``, or ``redis.client.Redis``
  (offsite retention is a pure replicator -- reads from disk, writes to
  remote, emits to bus only).
* Caller passes all policy knobs explicitly (same pattern as
  :func:`xops.backup.retention.prune_retained_dumps`) so the function
  is testable without a live config or live target.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from xops.backup.offsite.targets import OffsiteBackupTarget

_log = logging.getLogger("xops.backup.offsite.retention")


# -- Result dataclass ---------------------------------------------------------


@dataclass(frozen=True)
class OffsiteRetentionResult:
    """Outcome of a single offsite retention sweep.

    Attributes:
        pruned: Remote keys on which ``delete()`` was called and whose
            object-lock window had already lapsed (or no lock was
            configured).  Actual deletion is expected at the storage layer.
        skipped_lock: Remote keys on which ``delete()`` was called but
            whose object-lock WORM window has **not** yet lapsed.
            S3 returns HTTP 403 which :meth:`S3CompatibleTarget.delete`
            absorbs silently; the object remains on remote storage.
            The caller should record (log) these for audit without
            treating them as errors -- the next sweep after lock expiry
            will succeed.
        skipped_recent: Remote keys whose age is below ``retention_days``.
            ``delete()`` was **not** called.
    """

    pruned: tuple[str, ...]
    skipped_lock: tuple[str, ...]
    skipped_recent: tuple[str, ...]


# -- Public API ----------------------------------------------------------------


def prune_offsite_objects(
    *,
    target: OffsiteBackupTarget,
    objects: Sequence[tuple[str, datetime]],
    retention_days: int,
    object_lock_days: int,
    now: datetime,
    dry_run: bool = False,
) -> OffsiteRetentionResult:
    """Delete remote objects that have passed the retention window.

    For each ``(remote_key, uploaded_at)`` pair in *objects*:

    1. **Skip** objects whose age is less than ``retention_days`` -- record
       in ``skipped_recent``.
    2. **Attempt delete** for objects older than ``retention_days``:
       call ``target.delete(remote_key)`` unconditionally (the target's
       transport layer handles 403 / 404 silently).

       * If the object-lock window has lapsed (or there is no lock) ->
         record in ``pruned``.
       * If the object-lock window has **not** lapsed -> record in
         ``skipped_lock`` and emit a ``WARNING`` log entry.  The storage
         backend will silently refuse the delete (Object Lock enforces);
         a future sweep after the lock expires will succeed.

    Args:
        target: A concrete :class:`~xops.backup.offsite.targets.OffsiteBackupTarget`.
        objects: Sequence of ``(remote_key, uploaded_at_utc)`` pairs.
            ``uploaded_at_utc`` should be timezone-aware (UTC); naive
            datetimes are treated as UTC.
        retention_days: Objects older than this many full days are
            candidates for deletion.  Clamped to a minimum of 1.
        object_lock_days: WORM retention window in days.  0 means no
            object lock is configured and every expired object may be
            deleted immediately.
        now: Current time (timezone-aware UTC).  Injectable for
            deterministic tests.
        dry_run: When ``True`` the function computes the full partition
            and emits log lines but **never** calls ``target.delete()``.
            Use this when ``cfg.maint_backup_dry_run`` is set.

    Returns:
        An :class:`OffsiteRetentionResult` with three partitions.
    """
    keep_days = max(int(retention_days), 1)
    lock_days = max(int(object_lock_days), 0)

    pruned: list[str] = []
    skipped_lock: list[str] = []
    skipped_recent: list[str] = []

    for remote_key, uploaded_at in objects:
        # Normalise naive datetimes to UTC so age arithmetic is safe.
        if uploaded_at.tzinfo is None:
            uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)

        age = now - uploaded_at

        if age < timedelta(days=keep_days):
            skipped_recent.append(remote_key)
            continue

        # Determine whether the object-lock window has lapsed.
        lock_lapsed: bool = (
            lock_days == 0
            or (uploaded_at + timedelta(days=lock_days)) <= now
        )

        if dry_run:
            _log.info(
                "offsite_retention dry_run key=%r age_days=%.1f lock_lapsed=%s",
                remote_key,
                age.total_seconds() / 86_400,
                lock_lapsed,
            )
        else:
            target.delete(remote_key)
            _log.info(
                "offsite_retention delete key=%r age_days=%.1f lock_lapsed=%s",
                remote_key,
                age.total_seconds() / 86_400,
                lock_lapsed,
            )

        if lock_lapsed:
            pruned.append(remote_key)
        else:
            lock_expires_at = uploaded_at + timedelta(days=lock_days)
            _log.warning(
                "offsite_retention skipped_lock key=%r "
                "lock_expires_at=%s (delete is a silent no-op at storage "
                "layer; next sweep after lock expiry will remove the object)",
                remote_key,
                lock_expires_at.isoformat(),
            )
            skipped_lock.append(remote_key)

    return OffsiteRetentionResult(
        pruned=tuple(pruned),
        skipped_lock=tuple(skipped_lock),
        skipped_recent=tuple(skipped_recent),
    )
