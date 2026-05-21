"""ROADMAP §8.12 — unit tests for offsite retention sweeper.

Covers :func:`prune_offsite_objects` policy in isolation from the
``MaintBackupAgent`` so the age/lock partitioning, dry-run, and
naive-datetime normalisation stay asserted at the function boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from xops.backup.offsite.retention import (
    OffsiteRetentionResult,
    prune_offsite_objects,
)

UTC = timezone.utc


# -- Stub target --------------------------------------------------------------


class _RecordingTarget:
    """Stub that records every delete() call; never raises."""

    target_kind: str = "stub"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def upload(self, local_path, remote_key: str) -> None:  # pragma: no cover
        pass

    def delete(self, remote_key: str) -> None:
        self.deleted.append(remote_key)


NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def _make_objects(specs: list[tuple[str, int]]) -> list[tuple[str, datetime]]:
    """Build ``(remote_key, uploaded_at)`` pairs from ``(key, days_ago)``."""
    return [
        (key, NOW - timedelta(days=days))
        for key, days in specs
    ]


# -- Happy path ---------------------------------------------------------------


def test_recent_object_not_deleted() -> None:
    target = _RecordingTarget()
    objs = _make_objects([("backups/2026-05-20/dump.age", 1)])
    result = prune_offsite_objects(
        target=target,
        objects=objs,
        retention_days=7,
        object_lock_days=0,
        now=NOW,
    )
    assert "backups/2026-05-20/dump.age" in result.skipped_recent
    assert result.pruned == ()
    assert result.skipped_lock == ()
    assert target.deleted == []


def test_expired_no_lock_object_deleted() -> None:
    target = _RecordingTarget()
    objs = _make_objects([("backups/2026-04-10/dump.age", 41)])
    result = prune_offsite_objects(
        target=target,
        objects=objs,
        retention_days=7,
        object_lock_days=0,
        now=NOW,
    )
    assert "backups/2026-04-10/dump.age" in result.pruned
    assert result.skipped_lock == ()
    assert result.skipped_recent == ()
    assert "backups/2026-04-10/dump.age" in target.deleted


def test_expired_lapsed_lock_goes_to_pruned() -> None:
    # Uploaded 100 days ago; lock was 30 days -> lock lapsed 70 days ago.
    target = _RecordingTarget()
    objs = _make_objects([("backups/old/dump.age", 100)])
    result = prune_offsite_objects(
        target=target,
        objects=objs,
        retention_days=90,
        object_lock_days=30,
        now=NOW,
    )
    assert "backups/old/dump.age" in result.pruned
    assert result.skipped_lock == ()
    assert "backups/old/dump.age" in target.deleted


def test_expired_active_lock_goes_to_skipped_lock() -> None:
    # Uploaded 10 days ago; retention is 7d so it's expired by age policy,
    # but lock is 30d so lock has NOT lapsed yet.
    target = _RecordingTarget()
    objs = _make_objects([("backups/locked/dump.age", 10)])
    result = prune_offsite_objects(
        target=target,
        objects=objs,
        retention_days=7,
        object_lock_days=30,
        now=NOW,
    )
    assert "backups/locked/dump.age" in result.skipped_lock
    assert result.pruned == ()
    assert result.skipped_recent == ()
    # delete() is still called (storage backend enforces 403 silently).
    assert "backups/locked/dump.age" in target.deleted


def test_mixed_batch_partitioned_correctly() -> None:
    target = _RecordingTarget()
    objs = _make_objects([
        ("recent/dump.age", 3),      # too new
        ("old_unlocked/dump.age", 100),   # expired + no lock -> pruned
        ("old_locked/dump.age", 10),      # expired + active lock -> skipped_lock
        ("lapsed/dump.age", 50),          # expired + lapsed lock -> pruned
    ])
    result = prune_offsite_objects(
        target=target,
        objects=objs,
        retention_days=7,
        object_lock_days=30,
        now=NOW,
    )
    assert "recent/dump.age" in result.skipped_recent
    assert "old_unlocked/dump.age" in result.pruned
    assert "old_locked/dump.age" in result.skipped_lock
    assert "lapsed/dump.age" in result.pruned
    # delete called for expired candidates only.
    assert "recent/dump.age" not in target.deleted
    assert "old_unlocked/dump.age" in target.deleted
    assert "old_locked/dump.age" in target.deleted
    assert "lapsed/dump.age" in target.deleted


# -- Dry run ------------------------------------------------------------------


def test_dry_run_computes_partition_without_deleting() -> None:
    target = _RecordingTarget()
    objs = _make_objects([
        ("old/dump.age", 200),
        ("fresh/dump.age", 2),
    ])
    result = prune_offsite_objects(
        target=target,
        objects=objs,
        retention_days=90,
        object_lock_days=0,
        now=NOW,
        dry_run=True,
    )
    assert "old/dump.age" in result.pruned
    assert "fresh/dump.age" in result.skipped_recent
    # No actual deletes.
    assert target.deleted == []


# -- Edge cases ---------------------------------------------------------------


def test_empty_object_list_returns_empty_result() -> None:
    target = _RecordingTarget()
    result = prune_offsite_objects(
        target=target, objects=[], retention_days=7, object_lock_days=0, now=NOW
    )
    assert result == OffsiteRetentionResult((), (), ())
    assert target.deleted == []


def test_naive_datetime_treated_as_utc() -> None:
    """A naive uploaded_at should not crash; treated as UTC."""
    target = _RecordingTarget()
    naive_uploaded = (NOW - timedelta(days=100)).replace(tzinfo=None)
    result = prune_offsite_objects(
        target=target,
        objects=[("key/naive.age", naive_uploaded)],
        retention_days=7,
        object_lock_days=0,
        now=NOW,
    )
    assert "key/naive.age" in result.pruned


def test_retention_days_clamped_to_minimum_one() -> None:
    """retention_days <= 0 is treated as 1 (keep nothing older than 1 day)."""
    target = _RecordingTarget()
    # Uploaded 2 days ago; should be pruned even with retention_days=0.
    objs = _make_objects([("k/dump.age", 2)])
    result = prune_offsite_objects(
        target=target, objects=objs, retention_days=0, object_lock_days=0, now=NOW
    )
    assert "k/dump.age" in result.pruned


def test_lock_just_lapsed_boundary() -> None:
    """Object whose lock expires exactly now should go to pruned (not skipped_lock)."""
    target = _RecordingTarget()
    # Uploaded exactly 30 days ago; lock = 30 days -> expires exactly at NOW.
    uploaded_at = NOW - timedelta(days=30)
    result = prune_offsite_objects(
        target=target,
        objects=[("k/boundary.age", uploaded_at)],
        retention_days=7,
        object_lock_days=30,
        now=NOW,
    )
    assert "k/boundary.age" in result.pruned
    assert "k/boundary.age" not in result.skipped_lock


def test_lock_one_second_before_lapse_goes_to_skipped_lock() -> None:
    """Object whose lock expires one second after now stays in skipped_lock."""
    target = _RecordingTarget()
    uploaded_at = NOW - timedelta(days=30) + timedelta(seconds=1)
    result = prune_offsite_objects(
        target=target,
        objects=[("k/almost.age", uploaded_at)],
        retention_days=7,
        object_lock_days=30,
        now=NOW,
    )
    assert "k/almost.age" in result.skipped_lock
    assert "k/almost.age" not in result.pruned


# -- Adversarial --------------------------------------------------------------


def test_delete_raises_does_not_suppress_and_propagates() -> None:
    """Errors from target.delete() propagate (not swallowed by the sweeper)."""

    class _ErrorTarget:
        target_kind = "stub"
        def upload(self, lp, rk): pass
        def delete(self, rk): raise OSError("transport down")

    objs = _make_objects([("k/dump.age", 100)])
    with pytest.raises(OSError, match="transport down"):
        prune_offsite_objects(
            target=_ErrorTarget(),
            objects=objs,
            retention_days=7,
            object_lock_days=0,
            now=NOW,
        )


def test_prod_default_retention_days_from_config() -> None:
    """Profile-aware default: prod -> 90 days, mock -> 7 days."""
    import os
    from common.config import Config

    # Mock profile (default when NEGELIR_PROFILE is unset).
    os.environ.pop("NEGELIR_MAINT_BACKUP_OFFSITE_RETENTION_DAYS", None)
    os.environ["NEGELIR_PROFILE"] = "mock"
    cfg_mock = Config()
    assert cfg_mock.maint_backup_offsite_retention_days == 7

    os.environ["NEGELIR_PROFILE"] = "prod"
    cfg_prod = Config()
    assert cfg_prod.maint_backup_offsite_retention_days == 90

    # Restore
    os.environ.pop("NEGELIR_PROFILE", None)
