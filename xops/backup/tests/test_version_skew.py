"""Phase 8 §8.13.4 — restore-verify version-skew proof tests.

Five scenarios mandated by the ROADMAP proof-tests bullet:

(a) Gap within limit → pg_restore succeeds, forward migrations apply,
    verify.sql passes.
(b) Gap exceeds max → ``verify()`` returns ``{}``,
    ``last_refusal_info`` is set with ``kind="backup_dump_too_old"``.
(c) Legacy manifest (no migrations_at_dump_time) → verify runs without
    forward-migrate, result contains ``_legacy_manifest=1``.
(d) Gap exactly at limit (not exceeding) → allowed, forward migrations
    apply, verify succeeds.
(e) Gap = 0 (dump and in-tree match) → no forward migrations applied,
    verify.sql passes normally (no _legacy_manifest key).

All tests use a fake runner — no Docker, pg_dump, pg_restore, or psql
binaries are ever spawned.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pytest

from xops.backup.executors import (
    CHECKSUM_NAME,
    DUMP_DIR_NAME,
    ENCRYPTED_NAME,
    MANIFEST_NAME,
)
from xops.backup.verifier import LocalSubprocessVerifier, VersionGapRefusalError


# ── Shared test helpers ────────────────────────────────────────────────


@dataclass
class FakeRunner:
    """Minimal fake runner: programmable per argv[0] basename."""

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
            return subprocess.CompletedProcess(
                args=list(argv), returncode=0, stdout=b"", stderr=b"",
            )
        return handler(list(argv), env, cwd)


def _seed_window(
    tmp_path: Path,
    *,
    window: str = "w1",
    payload: bytes = b"BLOB",
    manifest_max_version: Optional[int] = None,
    include_manifest: bool = True,
) -> Path:
    """Create a minimal per-window directory with encrypted blob, checksum,
    and optionally a manifest with migrations_at_dump_time."""
    safe = window.replace(":", "_").replace("/", "_")
    wdir = tmp_path / safe
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / ENCRYPTED_NAME).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (wdir / CHECKSUM_NAME).write_text(f"{digest}  {ENCRYPTED_NAME}\n")
    if include_manifest:
        manifest: dict = {"fire_window_id": window, "format": "directory"}
        if manifest_max_version is not None:
            manifest["migrations_at_dump_time"] = {
                "max_version": manifest_max_version,
                "applied_versions": list(range(1, manifest_max_version + 1)),
                "repo_commit_sha": None,
            }
        (wdir / MANIFEST_NAME).write_text(
            json.dumps(manifest) + "\n", encoding="utf-8",
        )
    return wdir


def _seed_migrations(tmp_path: Path, *, versions: list[int]) -> Path:
    """Create a synthetic migrations directory with NNN_description.sql files."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir(exist_ok=True)
    for ver in versions:
        (mig_dir / f"{ver:03d}_test_migration.sql").write_text(
            f"-- migration {ver}\nSELECT {ver};\n", encoding="utf-8",
        )
    return mig_dir


def _seed_identity(tmp_path: Path) -> Path:
    p = tmp_path / "identity.txt"
    p.write_text("AGE-SECRET-KEY-1EXAMPLE\n")
    return p


def _seed_verify_sql(tmp_path: Path) -> Path:
    p = tmp_path / "verify.sql"
    p.write_text("SELECT 'matches', COUNT(*) FROM matches;\n")
    return p


def _make_age_handler(dump_dir: Optional[Path] = None) -> Any:
    """Return a fake ``age -d`` handler that writes a tar with a dump.d/ entry."""
    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        # Create the tar in a sibling staging area so it doesn't conflict
        # with the scratch dir itself.
        stage = out_path.parent / "_age_stage"
        stage.mkdir(parents=True, exist_ok=True)
        data_dir = stage / DUMP_DIR_NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "0001.dat").write_bytes(b"x")
        with tarfile.open(out_path, "w") as tar:
            tar.add(data_dir, arcname=DUMP_DIR_NAME)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")
    return fake_age


def _make_docker_handler() -> Any:
    """Return a fake docker handler that returns a port for 'port' subcommand."""
    def fake_docker(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "port" in argv:
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"0.0.0.0:54321\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")
    return fake_docker


def _make_psql_handler(output: bytes = b"matches,100\n") -> Any:
    """Return a fake psql handler that returns a fixed output for verify.sql."""
    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=output, stderr=b"",
        )
    return fake_psql


# ── (a) Gap within limit → forward migrations apply, verify.sql passes ─


def test_version_skew_within_limit_forward_migrates_and_verifies(
    tmp_path: Path,
) -> None:
    """Gap=4 (manifest=10, in_tree=14, max=5) → allowed.
    Forward migrations 011-014 must be applied (4 psql -f calls) before
    verify.sql. verify() returns the row-count dict (no _legacy_manifest).
    """
    # In-tree migrations: 001-014
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 15)))
    _seed_window(tmp_path, window="w1", manifest_max_version=10)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    migration_calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "-f" in argv:
            f_arg = argv[argv.index("-f") + 1]
            if "test_migration" in f_arg:
                migration_calls.append(os.path.basename(f_arg))
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=b"", stderr=b"",
                )
            # verify.sql
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"matches,42\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="w1")

    assert result == {"matches": 42}, f"unexpected result: {result}"
    assert "_legacy_manifest" not in result
    assert v.last_refusal_info is None

    # Verify 4 forward migrations applied in order: 011, 012, 013, 014
    assert len(migration_calls) == 4, f"expected 4 forward migrations, got: {migration_calls}"
    versions_applied = [int(n[:3]) for n in migration_calls]
    assert versions_applied == [11, 12, 13, 14], f"wrong migration order: {versions_applied}"


# ── (b) Gap exceeds max → {} + last_refusal_info=backup_dump_too_old ───


def test_version_skew_exceeds_max_refuses_with_correct_alert_info(
    tmp_path: Path,
) -> None:
    """Gap=10 (manifest=5, in_tree=15, max=5) → refuse.
    verify() returns {}, last_refusal_info.kind == 'backup_dump_too_old',
    no Docker container is started.
    """
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 16)))
    _seed_window(tmp_path, window="w2", manifest_max_version=5)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": _make_psql_handler(),
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="w2")

    assert result == {}, "backup_dump_too_old must return {}"
    assert v.last_refusal_info is not None
    assert v.last_refusal_info["kind"] == "backup_dump_too_old"
    assert v.last_refusal_info["version_gap"] == 10
    assert v.last_refusal_info["manifest_max_version"] == 5
    assert v.last_refusal_info["in_tree_max_version"] == 15
    assert v.last_refusal_info["max_gap"] == 5

    # Container must NOT have been spun up — fail-fast before decrypt.
    docker_calls = [c for c in runner.calls if os.path.basename(c[0]) == "docker"]
    assert all("run" not in c for c in docker_calls), (
        "no docker container should be started on version-gap refusal"
    )


# ── (c) Legacy manifest → skip forward-migrate, _legacy_manifest=1 ─────


def test_legacy_manifest_skips_forward_migrate_and_marks_result(
    tmp_path: Path,
) -> None:
    """Manifest without migrations_at_dump_time → legacy path.
    Forward-migration must be skipped. Result includes _legacy_manifest=1.
    No psql -f calls for migration files.
    """
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 12)))
    # Seed window with no migrations_at_dump_time (legacy manifest)
    _seed_window(tmp_path, window="w3", manifest_max_version=None)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    migration_calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "-f" in argv:
            f_arg = argv[argv.index("-f") + 1]
            if "test_migration" in f_arg:
                migration_calls.append(f_arg)
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"matches,7\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="w3")

    # Legacy manifest → result is non-empty (success) with sentinel key.
    assert result.get("_legacy_manifest") == 1
    assert result.get("matches") == 7
    assert v.last_refusal_info is None

    # No forward migration SQL files should have been applied.
    assert migration_calls == [], (
        f"legacy manifest must skip forward-migrate; got calls: {migration_calls}"
    )


# ── (d) Gap exactly at limit → allowed, forward migrations apply ────────


def test_version_skew_at_exact_limit_is_allowed(
    tmp_path: Path,
) -> None:
    """Gap == max_version_gap (=3) → still allowed (not > limit).
    Forward migrations apply normally.
    """
    mig_dir = _seed_migrations(tmp_path, versions=[1, 2, 3, 4, 5])
    _seed_window(tmp_path, window="w4", manifest_max_version=2)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    migration_calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "-f" in argv:
            f_arg = argv[argv.index("-f") + 1]
            if "test_migration" in f_arg:
                migration_calls.append(os.path.basename(f_arg))
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=b"", stderr=b"",
                )
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"matches,3\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=3,  # gap = 5-2 = 3, exactly at limit
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="w4")

    assert result.get("matches") == 3
    assert v.last_refusal_info is None
    # Migrations 003, 004, 005 applied (3 forward migrations)
    versions_applied = [int(n[:3]) for n in migration_calls]
    assert versions_applied == [3, 4, 5]


# ── (e) Gap = 0 → no forward migrations, clean verify.sql result ────────


def test_version_skew_zero_gap_runs_verify_without_forward_migrate(
    tmp_path: Path,
) -> None:
    """Gap = 0 (dump and in-tree at same version) → no forward migrations
    applied, verify.sql result returned as-is (no _legacy_manifest).
    """
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 12)))
    # manifest max_version == in_tree max_version == 11
    _seed_window(tmp_path, window="w5", manifest_max_version=11)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    migration_calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "-f" in argv:
            f_arg = argv[argv.index("-f") + 1]
            if "test_migration" in f_arg:
                migration_calls.append(f_arg)
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=b"", stderr=b"",
                )
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"matches,99\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="w5")

    assert result == {"matches": 99}
    assert "_legacy_manifest" not in result
    assert v.last_refusal_info is None
    assert migration_calls == [], (
        f"zero-gap must not apply any forward migrations; got: {migration_calls}"
    )


# ═══════════════════════════════════════════════════════════════════════
# §8.13.4 ROADMAP bullet 4 — Explicit named proof tests (a), (b), (c)
#
# These three tests are the canonical linkage between the ROADMAP bullet
# text and passing CI. They use the *exact* parameters from the bullet:
#   (a) synthetic dump at migration 010, in-tree at 014, gap=4 → succeed
#   (b) same setup with gap=10 (dump at 004) → refuse + alert
#   (c) manifest missing migration metadata → skip forward-migrate,
#       emit kind=backup_legacy_manifest (sentinel: _legacy_manifest=1)
# ═══════════════════════════════════════════════════════════════════════


def test_proof_a_gap4_restore_succeeds_applies_forward_migrations(
    tmp_path: Path,
) -> None:
    """ROADMAP §8.13.4 proof (a): dump at migration 010, in-tree at 014,
    gap=4, max_version_gap=5.

    Expectation: restore succeeds, migrations 011-014 apply in numeric
    order, verify.sql passes (returns non-empty row-count dict).
    ``_legacy_manifest`` must NOT appear in the result.
    """
    # In-tree has migrations 001-014; dump was taken at migration 010.
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 15)))
    _seed_window(tmp_path, window="proof_a", manifest_max_version=10)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    forward_applied: list[int] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "-f" in argv:
            sql_arg = argv[argv.index("-f") + 1]
            if "test_migration" in sql_arg:
                forward_applied.append(int(os.path.basename(sql_arg)[:3]))
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=b"", stderr=b"",
                )
            # verify.sql call
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"matches,200\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="proof_a")

    # Restore must succeed and return a non-empty row-count dict.
    assert result, f"proof (a): expected non-empty result, got: {result}"
    assert result.get("matches") == 200
    assert "_legacy_manifest" not in result, (
        "proof (a): _legacy_manifest must not appear when manifest is present"
    )
    assert v.last_refusal_info is None, (
        "proof (a): gap=4 is within max=5, no refusal expected"
    )
    # Exactly migrations 011, 012, 013, 014 must be applied in order.
    assert forward_applied == [11, 12, 13, 14], (
        f"proof (a): expected migrations [11,12,13,14] applied, got: {forward_applied}"
    )


def test_proof_b_gap10_refuses_with_alert(
    tmp_path: Path,
) -> None:
    """ROADMAP §8.13.4 proof (b): same setup as (a) but gap=10.

    Dump at migration 004, in-tree at 014, gap=10, max_version_gap=5.
    Expectation: verify() returns {}, last_refusal_info carries
    ``kind='backup_dump_too_old'``, no Docker container is started.
    """
    # In-tree has migrations 001-014; dump was taken at migration 004.
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 15)))
    _seed_window(tmp_path, window="proof_b", manifest_max_version=4)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": _make_psql_handler(),
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="proof_b")

    # Must refuse and return empty dict.
    assert result == {}, (
        f"proof (b): gap=10 > max=5 must return {{}}; got: {result}"
    )
    # Alert info must be populated with kind=backup_dump_too_old.
    assert v.last_refusal_info is not None, (
        "proof (b): last_refusal_info must be set on refusal"
    )
    assert v.last_refusal_info["kind"] == "backup_dump_too_old", (
        f"proof (b): expected kind='backup_dump_too_old', got: {v.last_refusal_info}"
    )
    assert v.last_refusal_info["version_gap"] == 10
    assert v.last_refusal_info["manifest_max_version"] == 4
    assert v.last_refusal_info["in_tree_max_version"] == 14
    assert v.last_refusal_info["max_gap"] == 5

    # No Docker container should have been spun up (fail-fast before decrypt).
    docker_run_calls = [
        c for c in runner.calls
        if os.path.basename(c[0]) == "docker" and "run" in c
    ]
    assert docker_run_calls == [], (
        "proof (b): no docker run must occur when version-gap refusal fires"
    )


def test_proof_c_legacy_manifest_skip_forward_migrate_emits_backup_legacy_manifest(
    tmp_path: Path,
) -> None:
    """ROADMAP §8.13.4 proof (c): manifest present but missing
    ``migrations_at_dump_time`` (legacy dump from before this revision).

    Expectation:
    - forward-migrate is skipped entirely (no psql -f <migration> calls)
    - verify.sql runs against the dump's schema as-is
    - result contains ``_legacy_manifest=1`` — the backing signal the
      agent uses to emit ``kind=backup_legacy_manifest, severity=info``
    - ``last_refusal_info`` is None (this is informational, not a refusal)
    """
    mig_dir = _seed_migrations(tmp_path, versions=list(range(1, 15)))
    # Legacy manifest: include the manifest file but WITHOUT migrations_at_dump_time.
    _seed_window(tmp_path, window="proof_c", manifest_max_version=None)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    forward_migration_calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "-f" in argv:
            sql_arg = argv[argv.index("-f") + 1]
            if "test_migration" in sql_arg:
                # Any forward migration call is a test failure.
                forward_migration_calls.append(os.path.basename(sql_arg))
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=b"", stderr=b"",
                )
            # verify.sql
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"matches,55\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": _make_age_handler(),
        "docker": _make_docker_handler(),
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
        max_version_gap=5,
        migrations_dir=mig_dir,
    )
    result = v.verify(fire_window_id="proof_c")

    # verify.sql must have run (non-empty result with real data).
    assert result, f"proof (c): expected non-empty result from legacy-manifest path; got: {result}"

    # _legacy_manifest=1 IS the backup_legacy_manifest emission:
    # the verifier sets this key when it detects a legacy manifest so the
    # MaintBackupAgent can emit maint.event.v1{kind=backup_legacy_manifest,
    # severity=info}.  A missing key means the legacy path was not taken.
    assert result.get("_legacy_manifest") == 1, (
        f"proof (c): _legacy_manifest=1 must be present (kind=backup_legacy_manifest "
        f"emission marker); got result: {result}"
    )
    assert result.get("matches") == 55

    # Not a refusal — last_refusal_info must be None.
    assert v.last_refusal_info is None, (
        "proof (c): legacy manifest is informational, not a refusal; "
        f"last_refusal_info should be None, got: {v.last_refusal_info}"
    )

    # Forward-migrate must NOT have been called (legacy path skips it).
    assert forward_migration_calls == [], (
        f"proof (c): forward-migrate must be skipped on legacy manifest; "
        f"got calls: {forward_migration_calls}"
    )
