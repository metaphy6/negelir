"""Phase 8 §8.3 slice 1c — backup-age gauge + pg_jobs/connlimit probe."""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pytest

from xops.backup.age_gauge import (
    CRIT_HOURS,
    WARN_HOURS,
    BackupAgeReport,
    compute_backup_age,
)
from xops.backup.role_probe import BackupRoleError, verify_backup_role


# ── Backup-age gauge ──────────────────────────────────────────────────


def _mk_complete_dump(root: Path, window_id: str) -> Path:
    d = root / window_id
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"status": "ok", "fire_window_id": window_id}),
        encoding="utf-8",
    )
    (d / "negelir.checksum.txt").write_text("deadbeef  blob\n")
    return d


def test_age_gauge_unknown_when_dir_missing(tmp_path: Path) -> None:
    rep = compute_backup_age(tmp_path / "absent")
    assert rep.severity == "unknown"
    assert rep.age_hours is None


def test_age_gauge_crit_when_no_completed_dumps(tmp_path: Path) -> None:
    (tmp_path / "20260101T000000Z").mkdir()  # incomplete (no manifest)
    rep = compute_backup_age(tmp_path)
    assert rep.severity == "crit"
    assert rep.last_success_window_id is None
    assert "no successful" in rep.reason


def test_age_gauge_picks_freshest_success(tmp_path: Path) -> None:
    _mk_complete_dump(tmp_path, "20260501T000000Z")
    _mk_complete_dump(tmp_path, "20260503T000000Z")  # newer
    _mk_complete_dump(tmp_path, "20260502T000000Z")
    now = _dt.datetime(2026, 5, 3, 12, 0, 0, tzinfo=_dt.timezone.utc)
    rep = compute_backup_age(tmp_path, now_utc=now)
    assert rep.last_success_window_id == "20260503T000000Z"
    assert rep.severity == "ok"
    assert rep.age_hours == pytest.approx(12.0, abs=0.01)


def test_age_gauge_warn_threshold(tmp_path: Path) -> None:
    _mk_complete_dump(tmp_path, "20260501T000000Z")
    now = _dt.datetime(2026, 5, 2, 8, 0, 0, tzinfo=_dt.timezone.utc)  # 32h
    rep = compute_backup_age(tmp_path, now_utc=now)
    assert rep.severity == "warn"
    assert rep.age_hours is not None and rep.age_hours >= WARN_HOURS


def test_age_gauge_crit_threshold(tmp_path: Path) -> None:
    _mk_complete_dump(tmp_path, "20260501T000000Z")
    now = _dt.datetime(2026, 5, 3, 12, 0, 0, tzinfo=_dt.timezone.utc)  # 60h
    rep = compute_backup_age(tmp_path, now_utc=now)
    assert rep.severity == "crit"
    assert rep.age_hours is not None and rep.age_hours >= CRIT_HOURS


def test_age_gauge_ignores_failed_manifest(tmp_path: Path) -> None:
    d = tmp_path / "20260501T000000Z"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"status": "failed"}))
    (d / "negelir.checksum.txt").write_text("x\n")
    rep = compute_backup_age(tmp_path)
    assert rep.severity == "crit"
    assert rep.last_success_window_id is None


def test_age_gauge_ignores_unparseable_dir_names(tmp_path: Path) -> None:
    (tmp_path / "not-a-window").mkdir()
    _mk_complete_dump(tmp_path, "20260501T000000Z")
    now = _dt.datetime(2026, 5, 1, 6, 0, 0, tzinfo=_dt.timezone.utc)
    rep = compute_backup_age(tmp_path, now_utc=now)
    assert rep.last_success_window_id == "20260501T000000Z"
    assert rep.severity == "ok"


def test_age_gauge_to_dict_roundtrip(tmp_path: Path) -> None:
    rep = BackupAgeReport(
        last_success_window_id="x", last_success_at_utc=None,
        age_hours=1.5, severity="ok", reason="r",
    )
    d = rep.to_dict()
    assert d["age_hours"] == 1.5
    assert d["severity"] == "ok"


# ── pg_jobs vs rolconnlimit probe ─────────────────────────────────────


@dataclass
class FakeRunner:
    """Replays scripted stdout per psql `-c` query substring."""

    responses: dict[str, bytes] = field(default_factory=dict)
    raise_on: Optional[str] = None
    calls: list[list[str]] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess[bytes]":
        self.calls.append(list(argv))
        sql = ""
        for i, a in enumerate(argv):
            if a == "-c" and i + 1 < len(argv):
                sql = argv[i + 1]
                break
        if self.raise_on and self.raise_on in sql:
            raise subprocess.CalledProcessError(
                2, list(argv), output=b"", stderr=b"boom",
            )
        for needle, out in self.responses.items():
            if needle in sql:
                return subprocess.CompletedProcess(
                    args=list(argv), returncode=0, stdout=out, stderr=b"",
                )
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout=b"", stderr=b"",
        )


def test_role_probe_connlimit_unlimited_passes() -> None:
    runner = FakeRunner(responses={
        "current_user": b"negelir_backup,off\n",
        "rolconnlimit": b"-1\n",
    })
    verify_backup_role(
        pg_dsn="postgresql://x@y/z", runner=runner,
        psql_binary="psql", pg_jobs=8,
    )
    assert any("rolconnlimit" in " ".join(c) for c in runner.calls)


def test_role_probe_connlimit_sufficient_passes() -> None:
    runner = FakeRunner(responses={
        "current_user": b"negelir_backup,off\n",
        "rolconnlimit": b"6\n",
    })
    verify_backup_role(
        pg_dsn="postgresql://x@y/z", runner=runner,
        psql_binary="psql", pg_jobs=4, headroom=2,
    )


def test_role_probe_connlimit_too_tight_refuses() -> None:
    runner = FakeRunner(responses={
        "current_user": b"negelir_backup,off\n",
        "rolconnlimit": b"5\n",
    })
    with pytest.raises(BackupRoleError, match="exceeds rolconnlimit"):
        verify_backup_role(
            pg_dsn="postgresql://x@y/z", runner=runner,
            psql_binary="psql", pg_jobs=4, headroom=2,
        )


def test_role_probe_connlimit_skipped_when_pg_jobs_none() -> None:
    runner = FakeRunner(responses={
        "current_user": b"negelir_backup,off\n",
        # no rolconnlimit key — would default to b"" if probed
    })
    verify_backup_role(
        pg_dsn="postgresql://x@y/z", runner=runner,
        psql_binary="psql", pg_jobs=None,
    )
    # Must NOT have probed connlimit.
    assert not any("rolconnlimit" in " ".join(c) for c in runner.calls)


def test_role_probe_connlimit_psql_failure_surfaces() -> None:
    runner = FakeRunner(
        responses={"current_user": b"negelir_backup,off\n"},
        raise_on="rolconnlimit",
    )
    with pytest.raises(BackupRoleError, match="connlimit probe failed"):
        verify_backup_role(
            pg_dsn="postgresql://x@y/z", runner=runner,
            psql_binary="psql", pg_jobs=4,
        )


def test_role_probe_connlimit_no_rows_refuses() -> None:
    runner = FakeRunner(responses={
        "current_user": b"negelir_backup,off\n",
        "rolconnlimit": b"\n",
    })
    with pytest.raises(BackupRoleError, match="no rows"):
        verify_backup_role(
            pg_dsn="postgresql://x@y/z", runner=runner,
            psql_binary="psql", pg_jobs=4,
        )


def test_role_probe_connlimit_non_int_refuses() -> None:
    runner = FakeRunner(responses={
        "current_user": b"negelir_backup,off\n",
        "rolconnlimit": b"not-a-number\n",
    })
    with pytest.raises(BackupRoleError, match="not an int"):
        verify_backup_role(
            pg_dsn="postgresql://x@y/z", runner=runner,
            psql_binary="psql", pg_jobs=4,
        )
