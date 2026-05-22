"""Phase 8 §8.3 — role-probe + wiring-factory proof tests."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pytest

from xops.backup.executors import LocalPgDumpExecutor
from xops.backup.role_probe import (
    BackupRoleError,
    EXPECTED_BACKUP_ROLE,
    verify_backup_role,
)
from xops.backup.wiring import (
    BackupWiringError,
    build_backup_drivers,
)


@dataclass
class FakeRunner:
    calls: list[list[str]] = field(default_factory=list)
    stdout: bytes = b""
    raise_called: bool = False
    raise_not_found: bool = False

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess[bytes]":
        self.calls.append(list(argv))
        if self.raise_not_found:
            raise FileNotFoundError("psql")
        if self.raise_called:
            raise subprocess.CalledProcessError(2, list(argv), output=b"", stderr=b"connection refused")
        return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout=self.stdout, stderr=b"")


# ── role probe ─────────────────────────────────────────────────────────


def test_role_probe_refuses_empty_dsn() -> None:
    with pytest.raises(BackupRoleError, match="pg_dsn is empty"):
        verify_backup_role(pg_dsn="", runner=FakeRunner())


def test_role_probe_happy_path() -> None:
    runner = FakeRunner(stdout=b"negelir_backup,off\n")
    verify_backup_role(pg_dsn="postgresql://x@y/z", runner=runner, psql_binary="psql")
    # argv shape: --tuples-only --no-align -F, -c "SELECT current_user, ..."
    call = runner.calls[0]
    assert "--tuples-only" in call
    assert "--no-align" in call
    assert "--field-separator=," in call
    assert any("current_user" in a for a in call)


def test_role_probe_refuses_wrong_role() -> None:
    runner = FakeRunner(stdout=b"app_owner,off\n")
    with pytest.raises(BackupRoleError, match="connected as 'app_owner'"):
        verify_backup_role(pg_dsn="postgresql://x@y/z", runner=runner, psql_binary="psql")


def test_role_probe_refuses_superuser() -> None:
    runner = FakeRunner(stdout=b"negelir_backup,on\n")
    with pytest.raises(BackupRoleError, match="superuser"):
        verify_backup_role(pg_dsn="postgresql://x@y/z", runner=runner, psql_binary="psql")


def test_role_probe_surfaces_psql_failure() -> None:
    runner = FakeRunner(raise_called=True)
    with pytest.raises(BackupRoleError, match="psql failed"):
        verify_backup_role(pg_dsn="postgresql://x@y/z", runner=runner, psql_binary="psql")


def test_role_probe_surfaces_missing_binary() -> None:
    runner = FakeRunner(raise_not_found=True)
    with pytest.raises(BackupRoleError, match="not found"):
        verify_backup_role(pg_dsn="postgresql://x@y/z", runner=runner, psql_binary="psql")


def test_role_probe_refuses_empty_psql_output() -> None:
    runner = FakeRunner(stdout=b"")
    with pytest.raises(BackupRoleError, match="empty output"):
        verify_backup_role(pg_dsn="postgresql://x@y/z", runner=runner, psql_binary="psql")


# ── wiring factory ────────────────────────────────────────────────────


@dataclass
class _StubCfg:
    maint_backup_pg_dsn: str = ""
    maint_backup_age_recipients_file: str = ""
    maint_backup_age_identity_file: str = ""
    maint_backup_verify_pg_image: str = "postgres:16-alpine"
    maint_backup_dir: str = "./data/backups"
    maint_backup_pg_jobs: int = 2
    maint_backup_prune_batch: int = 10_000
    sec_quarantine_ttl_days: int = 30
    maint_schema_snapshot_retention_days: int = 90
    swarm_dlq_pg_retention_days: int = 14
    maint_audit_retention_days: int = 365
    maint_runtime: str = "none"
    maint_backup_max_version_gap: int = 5
    # §8.14.9 nice-level + ionice knobs
    maint_backup_pg_dump_nice_level: int = 10
    maint_backup_pg_dump_ionice: bool = True


def test_wiring_returns_shim_when_dsn_empty() -> None:
    drivers = build_backup_drivers(_StubCfg())
    assert drivers.profile == "shim"
    assert drivers.dump is None
    assert drivers.verifier is None
    assert drivers.pruner is None


def test_wiring_refuses_missing_recipients(tmp_path: Path) -> None:
    cfg = _StubCfg(
        maint_backup_pg_dsn="postgresql://x@y/z",
        maint_backup_age_recipients_file=str(tmp_path / "absent.txt"),
        maint_backup_age_identity_file=str(tmp_path / "id.txt"),
    )
    with pytest.raises(BackupWiringError, match="recipients_file"):
        build_backup_drivers(cfg)


def test_wiring_refuses_missing_identity(tmp_path: Path) -> None:
    rec = tmp_path / "rec.txt"
    rec.write_text("age1pubkey\n")
    cfg = _StubCfg(
        maint_backup_pg_dsn="postgresql://x@y/z",
        maint_backup_age_recipients_file=str(rec),
        maint_backup_age_identity_file=str(tmp_path / "absent.key"),
    )
    with pytest.raises(BackupWiringError, match="identity_file"):
        build_backup_drivers(cfg)


def test_wiring_refuses_latest_image(tmp_path: Path) -> None:
    rec = tmp_path / "rec.txt"; rec.write_text("age1\n")
    ident = tmp_path / "id.key"; ident.write_text("AGE-SECRET\n")
    cfg = _StubCfg(
        maint_backup_pg_dsn="postgresql://x@y/z",
        maint_backup_age_recipients_file=str(rec),
        maint_backup_age_identity_file=str(ident),
        maint_backup_verify_pg_image="postgres:latest",
    )
    with pytest.raises(BackupWiringError, match=r"\*-latest"):
        build_backup_drivers(cfg)


def test_wiring_live_path_invokes_role_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rec = tmp_path / "rec.txt"; rec.write_text("age1\n")
    ident = tmp_path / "id.key"; ident.write_text("AGE-SECRET\n")
    cfg = _StubCfg(
        maint_backup_pg_dsn="postgresql://x@y/z",
        maint_backup_age_recipients_file=str(rec),
        maint_backup_age_identity_file=str(ident),
        maint_backup_dir=str(tmp_path / "backups"),
        maint_backup_pg_jobs=4,
    )
    called: dict[str, Any] = {}

    def fake_probe(*, pg_dsn: str, **_kw: Any) -> None:
        called["dsn"] = pg_dsn

    monkeypatch.setattr("xops.backup.wiring.verify_backup_role", fake_probe)
    drivers = build_backup_drivers(cfg)
    assert drivers.profile == "live"
    assert called["dsn"] == "postgresql://x@y/z"
    assert isinstance(drivers.dump, LocalPgDumpExecutor)
    assert drivers.dump.pg_jobs == 4
    assert drivers.dump.exclude_quarantine_data is True
    assert drivers.pruner is not None


def test_wiring_refuses_k8s_runtime_until_sidecar_lands(tmp_path: Path) -> None:
    rec = tmp_path / "rec.txt"; rec.write_text("age1\n")
    ident = tmp_path / "id.key"; ident.write_text("AGE-SECRET\n")
    cfg = _StubCfg(
        maint_backup_pg_dsn="postgresql://x@y/z",
        maint_backup_age_recipients_file=str(rec),
        maint_backup_age_identity_file=str(ident),
        maint_runtime="k8s",
    )
    with pytest.raises(BackupWiringError, match="SidecarVerifier"):
        build_backup_drivers(cfg)


# ── exclude_quarantine_data argv check ────────────────────────────────


def test_dump_argv_includes_exclude_quarantine_data(tmp_path: Path) -> None:
    rec = tmp_path / "rec.txt"; rec.write_text("age1\n")

    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"x")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        Path(argv[argv.index("-o") + 1]).write_bytes(b"BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    @dataclass
    class _R:
        calls: list[list[str]] = field(default_factory=list)
        def __call__(self, argv: Sequence[str], **_kw: Any) -> "subprocess.CompletedProcess[bytes]":
            self.calls.append(list(argv))
            head = os.path.basename(argv[0])
            if head == "pg_dump":
                return fake_pg_dump(list(argv))
            if head == "age":
                return fake_age(list(argv))
            return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")

    runner = _R()
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(rec),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
        nice_level=0,
        ionice_enabled=False,
    )
    ex.dump(fire_window_id="w1", dry_run=False)
    pg_call = next(c for c in runner.calls if os.path.basename(c[0]) == "pg_dump")
    assert "--exclude-table-data=quarantine_samples" in pg_call


def test_dump_argv_omits_exclude_when_disabled(tmp_path: Path) -> None:
    rec = tmp_path / "rec.txt"; rec.write_text("age1\n")

    def fake_pg_dump(argv: list[str]) -> "subprocess.CompletedProcess[bytes]":
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"x")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str]) -> "subprocess.CompletedProcess[bytes]":
        Path(argv[argv.index("-o") + 1]).write_bytes(b"BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    @dataclass
    class _R:
        calls: list[list[str]] = field(default_factory=list)
        def __call__(self, argv: Sequence[str], **_kw: Any) -> "subprocess.CompletedProcess[bytes]":
            self.calls.append(list(argv))
            head = os.path.basename(argv[0])
            if head == "pg_dump":
                return fake_pg_dump(list(argv))
            if head == "age":
                return fake_age(list(argv))
            return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")

    runner = _R()
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(rec),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
        exclude_quarantine_data=False,
        nice_level=0,
        ionice_enabled=False,
    )
    ex.dump(fire_window_id="w2", dry_run=False)
    pg_call = next(c for c in runner.calls if os.path.basename(c[0]) == "pg_dump")
    assert not any("--exclude-table-data" in a for a in pg_call)
