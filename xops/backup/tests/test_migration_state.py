"""Phase 8 §8.13.4 — migration-state manifest tests.

Covers:

(a) ``scan_in_tree_migrations`` with a synthetic dir.
(b) ``read_repo_commit_sha`` happy path + missing file.
(c) ``build_migrations_at_dump_time`` output shape.
(d) ``LocalPgDumpExecutor.dump`` writes ``migrations_at_dump_time`` in
    the manifest JSON (integration with executor).
(e) Missing ``build_metadata.json`` → ``repo_commit_sha=null`` in
    manifest + once-at-boot alert sentinel fires exactly once.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import pytest

import xops.backup.migration_state as _ms_module
from xops.backup.migration_state import (
    SEC_ALERT_BACKUP_COMMIT_SHA_UNAVAILABLE,
    build_migrations_at_dump_time,
    consume_commit_sha_unavailable_alert,
    read_repo_commit_sha,
    scan_in_tree_migrations,
)
from xops.backup.executors import (
    ENCRYPTED_NAME,
    MANIFEST_NAME,
    LocalPgDumpExecutor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_migrations_dir(tmp_path: Path, filenames: list[str]) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    for fn in filenames:
        (d / fn).write_text("-- stub", encoding="utf-8")
    return d


def _make_build_metadata(tmp_path: Path, sha: str | None) -> Path:
    p = tmp_path / "build_metadata.json"
    data: dict = {"repo_commit_sha": sha, "built_at": "2026-05-21T00:00:00Z"}
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# scan_in_tree_migrations
# ---------------------------------------------------------------------------

def test_scan_migrations_standard_set(tmp_path: Path) -> None:
    mdir = _make_migrations_dir(tmp_path, [
        "001_initial.sql",
        "002_players.sql",
        "003_schema_snapshots.sql",
    ])
    result = scan_in_tree_migrations(migrations_dir=mdir)
    assert result["max_version"] == 3
    assert result["applied_versions"] == [1, 2, 3]


def test_scan_migrations_empty_dir(tmp_path: Path) -> None:
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    result = scan_in_tree_migrations(migrations_dir=mdir)
    assert result["max_version"] == 0
    assert result["applied_versions"] == []


def test_scan_migrations_missing_dir(tmp_path: Path) -> None:
    result = scan_in_tree_migrations(migrations_dir=tmp_path / "nonexistent")
    assert result["max_version"] == 0
    assert result["applied_versions"] == []


def test_scan_migrations_non_matching_files_skipped(tmp_path: Path) -> None:
    mdir = _make_migrations_dir(tmp_path, [
        "001_initial.sql",
        "README.md",
        "not_a_migration.sql",
        "002_players.sql",
    ])
    result = scan_in_tree_migrations(migrations_dir=mdir)
    assert result["max_version"] == 2
    assert result["applied_versions"] == [1, 2]


def test_scan_migrations_real_repo() -> None:
    """Scans the actual migrations/ directory; must find at least 011."""
    result = scan_in_tree_migrations()
    assert result["max_version"] >= 11
    assert 11 in result["applied_versions"]


# ---------------------------------------------------------------------------
# read_repo_commit_sha
# ---------------------------------------------------------------------------

def test_read_commit_sha_present(tmp_path: Path) -> None:
    p = _make_build_metadata(tmp_path, "abc123def456")
    sha = read_repo_commit_sha(build_metadata_path=p)
    assert sha == "abc123def456"


def test_read_commit_sha_missing_file(tmp_path: Path) -> None:
    sha = read_repo_commit_sha(build_metadata_path=tmp_path / "nosuchfile.json")
    assert sha is None


def test_read_commit_sha_null_value(tmp_path: Path) -> None:
    p = _make_build_metadata(tmp_path, None)
    sha = read_repo_commit_sha(build_metadata_path=p)
    assert sha is None


def test_read_commit_sha_empty_string(tmp_path: Path) -> None:
    p = tmp_path / "build_metadata.json"
    p.write_text(json.dumps({"repo_commit_sha": ""}), encoding="utf-8")
    sha = read_repo_commit_sha(build_metadata_path=p)
    assert sha is None


def test_read_commit_sha_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "build_metadata.json"
    p.write_text("not valid json {{{", encoding="utf-8")
    sha = read_repo_commit_sha(build_metadata_path=p)
    assert sha is None


# ---------------------------------------------------------------------------
# build_migrations_at_dump_time
# ---------------------------------------------------------------------------

def test_build_migrations_at_dump_time_full(tmp_path: Path) -> None:
    mdir = _make_migrations_dir(tmp_path, ["001_a.sql", "002_b.sql"])
    bmp = _make_build_metadata(tmp_path, "deadbeef")
    result = build_migrations_at_dump_time(
        migrations_dir=mdir, build_metadata_path=bmp
    )
    assert result["max_version"] == 2
    assert result["applied_versions"] == [1, 2]
    assert result["repo_commit_sha"] == "deadbeef"


def test_build_migrations_at_dump_time_no_sha(tmp_path: Path) -> None:
    mdir = _make_migrations_dir(tmp_path, ["001_a.sql"])
    result = build_migrations_at_dump_time(
        migrations_dir=mdir,
        build_metadata_path=tmp_path / "absent.json",
    )
    assert result["max_version"] == 1
    assert result["repo_commit_sha"] is None


# ---------------------------------------------------------------------------
# consume_commit_sha_unavailable_alert — module-level sentinel
# ---------------------------------------------------------------------------

def test_sentinel_returns_true_once_then_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sentinel fires True exactly once per process lifetime when sha is absent."""
    # Reset the module-level sentinel so this test is not order-dependent.
    monkeypatch.setattr(_ms_module, "_COMMIT_SHA_ALERT_EMITTED", False)
    absent = tmp_path / "absent.json"
    assert consume_commit_sha_unavailable_alert(build_metadata_path=absent) is True
    assert consume_commit_sha_unavailable_alert(build_metadata_path=absent) is False
    assert consume_commit_sha_unavailable_alert(build_metadata_path=absent) is False


def test_sentinel_does_not_fire_when_sha_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ms_module, "_COMMIT_SHA_ALERT_EMITTED", False)
    bmp = _make_build_metadata(tmp_path, "sha123")
    assert consume_commit_sha_unavailable_alert(build_metadata_path=bmp) is False
    # sha present — sentinel not flipped
    assert _ms_module._COMMIT_SHA_ALERT_EMITTED is False


# ---------------------------------------------------------------------------
# LocalPgDumpExecutor — manifest includes migrations_at_dump_time
# ---------------------------------------------------------------------------


def _write_recipients(tmp_path: Path) -> Path:
    p = tmp_path / "recipients.txt"
    p.write_text("age1testpubkey\n", encoding="utf-8")
    return p


def _make_fake_pg_dump_and_age(
) -> tuple[
    "Callable[[list[str], Any, Any], subprocess.CompletedProcess[bytes]]",
    "Callable[[list[str], Any, Any], subprocess.CompletedProcess[bytes]]",
]:
    """Return (fake_pg_dump, fake_age) handlers for FakeRunner."""

    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        # pg_jobs=1 → custom format → --file <single-file-path>
        file_idx = argv.index("--file")
        out_path = Path(argv[file_idx + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake-dump-content")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"AGE-ENCRYPTED-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    return fake_pg_dump, fake_age


@dataclass
class _FakeRunner:
    calls: list[list[str]] = field(default_factory=list)
    handlers: dict[str, Any] = field(default_factory=dict)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess[bytes]":
        self.calls.append(list(argv))
        head = os.path.basename(argv[0])
        handler = self.handlers.get(head)
        if handler is None:
            return subprocess.CompletedProcess(args=list(argv), returncode=0, stdout=b"", stderr=b"")
        return handler(list(argv), env, cwd)


def test_manifest_includes_migrations_at_dump_time(tmp_path: Path) -> None:
    """LocalPgDumpExecutor writes migrations_at_dump_time in manifest.json."""
    mdir = _make_migrations_dir(tmp_path, [
        "001_initial.sql",
        "010_pattern_allowlist.sql",
        "011_backup_role.sql",
    ])
    bmp = _make_build_metadata(tmp_path, "cafebabe")
    fake_pg_dump, fake_age = _make_fake_pg_dump_and_age()

    executor = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://fake/db",
        pg_jobs=1,
        age_recipients_file=str(_write_recipients(tmp_path)),
        runner=_FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": fake_age}),
        pg_dump_binary="pg_dump",
        age_binary="age",
        migrations_dir=mdir,
        build_metadata_path=bmp,
    )

    executor.dump(fire_window_id="2026-05-21T03:00:00", dry_run=False)

    backup_root = tmp_path / "backups"
    manifests = list(backup_root.rglob(MANIFEST_NAME))
    assert len(manifests) == 1, f"Expected 1 manifest, found: {manifests}"
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))

    assert "migrations_at_dump_time" in manifest
    madt = manifest["migrations_at_dump_time"]
    assert madt["max_version"] == 11
    assert set(madt["applied_versions"]) == {1, 10, 11}
    assert madt["repo_commit_sha"] == "cafebabe"


def test_manifest_null_sha_when_build_metadata_absent(tmp_path: Path) -> None:
    """When build_metadata.json is absent, repo_commit_sha is null in manifest."""
    mdir = _make_migrations_dir(tmp_path, ["001_initial.sql"])
    absent_bmp = tmp_path / "absent_build_metadata.json"
    fake_pg_dump, fake_age = _make_fake_pg_dump_and_age()

    executor = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://fake/db",
        pg_jobs=1,
        age_recipients_file=str(_write_recipients(tmp_path)),
        runner=_FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": fake_age}),
        pg_dump_binary="pg_dump",
        age_binary="age",
        migrations_dir=mdir,
        build_metadata_path=absent_bmp,
    )

    executor.dump(fire_window_id="2026-05-21T03:00:01", dry_run=False)

    backup_root = tmp_path / "backups"
    manifests = list(backup_root.rglob(MANIFEST_NAME))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))

    madt = manifest["migrations_at_dump_time"]
    assert madt["repo_commit_sha"] is None
    assert madt["max_version"] == 1
