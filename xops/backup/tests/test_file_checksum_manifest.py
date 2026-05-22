"""Phase 8 §8.14.2 — per-file dump checksum manifest proof tests.

Three scenarios mandated by the ROADMAP proof-tests bullet:

(a) Bit-flip inside dump dir (before tar) → inner manifest detects the
    mismatch, ``verify()`` returns ``{}``,
    ``last_file_manifest_failures`` is set, quarantine renames the dir.
(b) Bit-flip in the encrypted tarball (after tar+age) → outer
    checksum guard catches it, ``verify()`` returns ``{}``,
    ``last_file_manifest_failures`` is None (never reached).
(c) Legacy dump with no inner manifest → ``verify()`` sets
    ``last_legacy_no_file_manifest=True``, ``last_file_manifest_failures``
    stays None, and verify proceeds normally.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from xops.backup.executors import (
    CHECKSUM_NAME,
    DUMP_DIR_NAME,
    ENCRYPTED_NAME,
    FILE_CHECKSUM_MANIFEST_NAME,
    MANIFEST_NAME,
    quarantine_failed_dump_dir,
)
from xops.backup.verifier import (
    FileManifestCorruptionError,
    LocalSubprocessVerifier,
)


# ── Shared helpers ─────────────────────────────────────────────────────


@dataclass
class FakeRunner:
    """Minimal fake runner — programmable per argv[0] basename."""

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
        import os
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
    payload: bytes = b"ENCRYPTED_BLOB",
    manifest_max_version: Optional[int] = None,
) -> Path:
    """Create a minimal window dir with encrypted blob + correct outer checksum + manifest.json."""
    safe = window.replace(":", "_").replace("/", "_")
    wdir = tmp_path / safe
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / ENCRYPTED_NAME).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (wdir / CHECKSUM_NAME).write_text(f"{digest}  {ENCRYPTED_NAME}\n")
    manifest: dict = {"fire_window_id": window, "format": "directory"}
    if manifest_max_version is not None:
        manifest["migrations_at_dump_time"] = {
            "max_version": manifest_max_version,
            "applied_versions": list(range(1, manifest_max_version + 1)),
            "repo_commit_sha": None,
        }
    (wdir / MANIFEST_NAME).write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return wdir


def _seed_migrations(tmp_path: Path, *, versions: list[int]) -> Path:
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir(exist_ok=True)
    for ver in versions:
        (mig_dir / f"{ver:03d}_test.sql").write_text(
            f"-- v{ver}\nSELECT {ver};\n", encoding="utf-8",
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


def _make_age_handler_with_manifest(
    *,
    original_content: bytes,
    corrupt: bool = False,
) -> Any:
    """Fake age -d that writes a tar with dump.d/ + inner per-file manifest.

    If ``corrupt=True``, the extracted dump file has its first byte
    XOR'd so its SHA-256 differs from what the manifest records.
    This simulates a bit-flip that happened between pg_dump writing the
    file and the tar pipeline.
    """
    original_digest = hashlib.sha256(original_content).hexdigest()
    actual_bytes = (
        bytes([original_content[0] ^ 0xFF]) + original_content[1:]
        if corrupt
        else original_content
    )

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        stage = out_path.parent / "_age_stage"
        stage.mkdir(parents=True, exist_ok=True)
        data_dir = stage / DUMP_DIR_NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "data.dat").write_bytes(actual_bytes)
        # Manifest always records the ORIGINAL (correct) hash; when
        # corrupt=True the file on disk has different bytes → mismatch.
        (data_dir / FILE_CHECKSUM_MANIFEST_NAME).write_text(
            f"{original_digest}  data.dat\n",
            encoding="utf-8",
        )
        with tarfile.open(out_path, "w") as tar:
            tar.add(data_dir, arcname=DUMP_DIR_NAME)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    return fake_age


def _make_age_handler_legacy() -> Any:
    """Fake age -d that writes a tar with dump.d/ but NO inner manifest (legacy)."""

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        stage = out_path.parent / "_age_stage"
        stage.mkdir(parents=True, exist_ok=True)
        data_dir = stage / DUMP_DIR_NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "data.dat").write_bytes(b"pg_dump_data")
        # Intentionally omit FILE_CHECKSUM_MANIFEST_NAME.
        with tarfile.open(out_path, "w") as tar:
            tar.add(data_dir, arcname=DUMP_DIR_NAME)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    return fake_age


def _make_docker_handler() -> Any:
    def fake_docker(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "port" in argv:
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"0.0.0.0:54321\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")
    return fake_docker


def _make_psql_handler(output: bytes = b"matches,42\n") -> Any:
    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=output, stderr=b"",
        )
    return fake_psql


# ── (a) Bit-flip inside dump dir → inner manifest detects corruption ──


def test_inner_manifest_detects_dump_file_bit_flip(tmp_path: Path) -> None:
    """Corrupt a file BEFORE tar+age → inner manifest SHA-256 mismatch.

    verify() must return {}, last_file_manifest_failures must have one
    entry for the corrupted file, and quarantine_failed_dump_dir must
    rename the window dir.
    """
    original = b"pg_dump_parallel_worker_output"
    mig_dir = _seed_migrations(tmp_path, versions=[1])
    _seed_window(tmp_path, manifest_max_version=1)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    runner = FakeRunner(handlers={
        "age": _make_age_handler_with_manifest(original_content=original, corrupt=True),
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        migrations_dir=mig_dir,
        verify_sql_path=str(verify_sql),
    )
    result = v.verify(fire_window_id="w1")

    assert result == {}
    assert v.last_file_manifest_failures is not None
    assert len(v.last_file_manifest_failures) == 1
    failure = v.last_file_manifest_failures[0]
    assert failure["file"] == "data.dat"
    # File exists but SHA-256 differs (not "missing").
    assert failure["actual"] != "missing"
    assert failure["expected"] != failure["actual"]

    # Caller quarantines the window dir after detecting corruption.
    quarantined = quarantine_failed_dump_dir(
        backup_dir=str(tmp_path), fire_window_id="w1",
    )
    assert quarantined is not None
    assert quarantined.name == "w1.failed"
    assert quarantined.is_dir()
    assert not (tmp_path / "w1").exists()


# ── (b) Bit-flip in encrypted tarball → outer checksum catches it ─────


def test_outer_checksum_guards_encrypted_tarball_bit_flip(tmp_path: Path) -> None:
    """Corrupt the encrypted blob AFTER it was written → outer checksum mismatch.

    verify() must return {} and last_file_manifest_failures must stay
    None — the inner manifest check is never reached.
    """
    mig_dir = _seed_migrations(tmp_path, versions=[1])
    wdir = _seed_window(tmp_path, payload=b"valid_encrypted_content", manifest_max_version=1)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    # Corrupt the blob AFTER seeding so the recorded checksum no longer matches.
    enc = wdir / ENCRYPTED_NAME
    data = enc.read_bytes()
    enc.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])

    runner = FakeRunner(handlers={})
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        migrations_dir=mig_dir,
        verify_sql_path=str(verify_sql),
    )
    result = v.verify(fire_window_id="w1")

    # Outer checksum caught it; inner manifest check was never reached.
    assert result == {}
    assert v.last_file_manifest_failures is None


# ── (c) Legacy dump — no inner manifest → flag set, verify proceeds ───


def test_legacy_dump_no_inner_manifest_sets_flag(tmp_path: Path) -> None:
    """Dump tarball has no FILE_CHECKSUM_MANIFEST_NAME (pre-§8.14.2 dump).

    verify() must set last_legacy_no_file_manifest=True,
    last_file_manifest_failures must stay None, and the rest of the
    verify pipeline must continue (result is non-empty on success).
    """
    # manifest_max_version=None → legacy outer manifest (no migrations_at_dump_time),
    # so the version-skew check is skipped and we focus solely on the file-manifest path.
    mig_dir = _seed_migrations(tmp_path, versions=[1])
    _seed_window(tmp_path)
    identity = _seed_identity(tmp_path)
    verify_sql = _seed_verify_sql(tmp_path)

    runner = FakeRunner(handlers={
        "age": _make_age_handler_legacy(),
        "docker": _make_docker_handler(),
        "psql": _make_psql_handler(b"matches,42\n"),
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=runner,
        migrations_dir=mig_dir,
        verify_sql_path=str(verify_sql),
    )
    result = v.verify(fire_window_id="w1")

    # Flag set, no corruption failures raised.
    assert v.last_legacy_no_file_manifest is True
    assert v.last_file_manifest_failures is None
    # Verify continued past the manifest check and returned row-count data.
    assert result != {}


# ── Adversarial: FileManifestCorruptionError carries failures list ─────


def test_file_manifest_corruption_error_carries_failures() -> None:
    """FileManifestCorruptionError is importable, holds the failures list,
    and its ``failures`` attribute is the same object passed to the constructor."""
    failures = [{"file": "x", "expected": "aa", "actual": "bb"}]
    exc = FileManifestCorruptionError("boom", failures=failures)
    assert exc.failures is failures
    assert "boom" in str(exc)
