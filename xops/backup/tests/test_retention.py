"""Phase 8 §8.3 — `xops.backup.retention` unit tests.

Covers the GFS-light policy in isolation from the
`MaintBackupAgent` so the partition rules (date parsing, recent-day
window, Sunday tier, quarantine preservation, dry-run) stay
asserted at the function boundary even if the agent re-wires.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from xops.backup.executors import FAILED_DIR_SUFFIX
from xops.backup.retention import (
    RetentionResult,
    prune_retained_dumps,
)


UTC = timezone.utc


def _mk(base: Path, name: str) -> Path:
    p = base / name
    p.mkdir()
    (p / "dump.tar.age").write_bytes(b"\x00")
    return p


def test_missing_backup_dir_returns_empty(tmp_path: Path) -> None:
    res = prune_retained_dumps(
        backup_dir=tmp_path / "does-not-exist",
        keep_days=14, keep_weeks=4,
        now=datetime(2025, 5, 1, tzinfo=UTC),
    )
    assert res == RetentionResult((), (), (), ())


def test_recent_dumps_kept_old_pruned(tmp_path: Path) -> None:
    _mk(tmp_path, "pod_2025-05-01")  # today
    _mk(tmp_path, "pod_2025-04-30")  # yesterday
    _mk(tmp_path, "pod_2025-04-01")  # old non-Sunday
    res = prune_retained_dumps(
        backup_dir=tmp_path,
        keep_days=3, keep_weeks=0,
        now=datetime(2025, 5, 1, tzinfo=UTC),
    )
    assert "pod_2025-04-01" in res.pruned
    assert "pod_2025-05-01" in res.kept
    assert "pod_2025-04-30" in res.kept
    assert not (tmp_path / "pod_2025-04-01").exists()


def test_weekly_sundays_preserved_within_quota(tmp_path: Path) -> None:
    # 2025-04-27, 2025-04-20, 2025-04-13, 2025-04-06 are all Sundays.
    sundays = ["2025-04-27", "2025-04-20", "2025-04-13", "2025-04-06"]
    for d in sundays:
        _mk(tmp_path, f"pod_{d}")
    # Today is Wed 2025-04-30; keep_days=1 makes them all "old".
    res = prune_retained_dumps(
        backup_dir=tmp_path, keep_days=1, keep_weeks=2,
        now=datetime(2025, 4, 30, tzinfo=UTC),
    )
    # Two most recent Sundays survive.
    assert "pod_2025-04-27" in res.kept
    assert "pod_2025-04-20" in res.kept
    # Older Sundays beyond the weekly quota are pruned.
    assert "pod_2025-04-13" in res.pruned
    assert "pod_2025-04-06" in res.pruned


def test_quarantined_dirs_never_pruned(tmp_path: Path) -> None:
    quarantined = f"pod_2024-01-01{FAILED_DIR_SUFFIX}"
    _mk(tmp_path, quarantined)
    res = prune_retained_dumps(
        backup_dir=tmp_path, keep_days=1, keep_weeks=0,
        now=datetime(2025, 5, 1, tzinfo=UTC),
    )
    assert quarantined in res.skipped_quarantine
    assert quarantined in res.kept
    assert quarantined not in res.pruned
    assert (tmp_path / quarantined).is_dir()


def test_unparseable_dirs_kept_and_reported(tmp_path: Path) -> None:
    _mk(tmp_path, "scratch")  # no date
    _mk(tmp_path, "verify-key-archive")
    res = prune_retained_dumps(
        backup_dir=tmp_path, keep_days=1, keep_weeks=0,
        now=datetime(2025, 5, 1, tzinfo=UTC),
    )
    assert "scratch" in res.unparseable
    assert "verify-key-archive" in res.unparseable
    assert res.pruned == ()


def test_dry_run_reports_but_does_not_delete(tmp_path: Path) -> None:
    old = _mk(tmp_path, "pod_2024-12-01")  # ancient non-Sunday
    res = prune_retained_dumps(
        backup_dir=tmp_path, keep_days=1, keep_weeks=0,
        now=datetime(2025, 5, 1, tzinfo=UTC),
        dry_run=True,
    )
    assert "pod_2024-12-01" in res.pruned
    # On-disk dir survives despite the report.
    assert old.is_dir()


def test_hidden_dirs_and_files_ignored(tmp_path: Path) -> None:
    (tmp_path / ".verify_keys").mkdir()
    (tmp_path / "audit.csv").write_text("x")
    res = prune_retained_dumps(
        backup_dir=tmp_path, keep_days=1, keep_weeks=0,
        now=datetime(2025, 5, 1, tzinfo=UTC),
    )
    assert res == RetentionResult((), (), (), ())


def test_keep_days_clamps_to_minimum_one(tmp_path: Path) -> None:
    _mk(tmp_path, "pod_2025-05-01")
    res = prune_retained_dumps(
        backup_dir=tmp_path, keep_days=0, keep_weeks=0,
        now=datetime(2025, 5, 1, tzinfo=UTC),
    )
    # Today's dump still inside the (clamped) 1-day window.
    assert "pod_2025-05-01" in res.kept
    assert res.pruned == ()


# ── §8.3 weekly cold-verify: oldest_retained_sunday_dump ─────────────


from xops.backup.retention import oldest_retained_sunday_dump


def test_oldest_sunday_returns_none_when_dir_missing(tmp_path: Path) -> None:
    assert oldest_retained_sunday_dump(backup_dir=tmp_path / "nope") is None


def test_oldest_sunday_returns_none_when_no_sundays(tmp_path: Path) -> None:
    # 2025-05-01 is a Thursday, 2025-05-02 a Friday — no Sundays.
    _mk(tmp_path, "pod_2025-05-01")
    _mk(tmp_path, "pod_2025-05-02")
    assert oldest_retained_sunday_dump(backup_dir=tmp_path) is None


def test_oldest_sunday_picks_earliest_sunday(tmp_path: Path) -> None:
    # 2025-04-06, 2025-04-13, 2025-04-20, 2025-04-27 are all Sundays.
    _mk(tmp_path, "pod_2025-04-13")
    _mk(tmp_path, "pod_2025-04-06")  # oldest
    _mk(tmp_path, "pod_2025-04-27")
    _mk(tmp_path, "pod_2025-05-01")  # Thursday — must be ignored
    got = oldest_retained_sunday_dump(backup_dir=tmp_path)
    assert got is not None
    day, name = got
    assert day == datetime(2025, 4, 6, tzinfo=UTC)
    assert name == "pod_2025-04-06"


def test_oldest_sunday_skips_quarantined_and_unparseable(tmp_path: Path) -> None:
    # Quarantined Sunday must be ignored even though it is the oldest.
    failed_name = f"pod_2025-04-06{FAILED_DIR_SUFFIX}"
    _mk(tmp_path, failed_name)
    _mk(tmp_path, "pod_2025-04-13")  # Sunday — should win
    _mk(tmp_path, "pod_garbage_no_date")  # unparseable
    got = oldest_retained_sunday_dump(backup_dir=tmp_path)
    assert got is not None
    _, name = got
    assert name == "pod_2025-04-13"
