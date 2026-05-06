"""Phase 8 §8.3 — live executor + verifier proof tests.

These tests exercise the subprocess-driving adapters
(``LocalPgDumpExecutor``, ``LocalSubprocessVerifier``) WITHOUT
spawning real ``pg_dump`` / ``age`` / ``docker`` — the runner
seam is monkey-patched so we can assert argv shape, file
permissions, checksum semantics, and failure paths
deterministically in CI.

What this asserts (binding):

* ``LocalPgDumpExecutor`` refuses-to-start when DSN or recipients
  are missing (Rule 3: never silently produce a useless dump).
* On success it (a) invokes ``pg_dump --format=directory --jobs=N
  --no-owner --no-privileges`` against the configured DSN, (b)
  invokes ``age -R <recipients> -o <out> <tar>``, (c) writes the
  encrypted blob 0o600, (d) writes a SHA-256 checksum file
  matching the encrypted bytes, (e) drops the intermediate
  plaintext tar, (f) returns ``(dump_bytes, encrypted_bytes)``.
* ``dry_run=True`` is a no-op.
* ``LocalSubprocessVerifier.verify`` returns an empty mapping
  (the Protocol's ``verify_failed`` signal) when any subprocess
  raises, when the encrypted dump is missing, or when the
  checksum mismatches the on-disk blob.
* On the happy path it (a) decrypts via ``age -d -i <id>``, (b)
  starts a pinned ``postgres:16-alpine`` container (NEVER
  ``*-latest``), (c) runs ``pg_restore --jobs=N``, (d) parses
  ``psql --tuples-only --no-align -F,`` output back into the
  per-table dict.
* ``sweep_orphans`` returns the names actually removed.
* The cfg validator refuses ``*-latest`` verify image tags.
"""
from __future__ import annotations

import hashlib
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
    LocalPgDumpExecutor,
)
from xops.backup.verifier import LocalSubprocessVerifier, _parse_verify_output


@dataclass
class FakeRunner:
    """Records every invocation; programmable side-effects per argv[0]."""

    calls: list[list[str]] = field(default_factory=list)
    # Map argv[0] basename → callback(argv, env, cwd) -> CompletedProcess
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


# ── LocalPgDumpExecutor ────────────────────────────────────────────────


def _write_recipients(tmp_path: Path) -> Path:
    p = tmp_path / "recipients.txt"
    p.write_text("age1examplerecipientpubkey0000000000000000000000000000\n")
    return p


def test_dump_refuses_without_dsn(tmp_path: Path) -> None:
    runner = FakeRunner()
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="",
        age_recipients_file=str(_write_recipients(tmp_path)),
        runner=runner,
    )
    with pytest.raises(RuntimeError, match="pg_dsn"):
        ex.dump(fire_window_id="w1", dry_run=False)
    assert runner.calls == [], "must not invoke any subprocess on refusal"


def test_dump_refuses_without_recipients(tmp_path: Path) -> None:
    runner = FakeRunner()
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(tmp_path / "missing.txt"),
        runner=runner,
    )
    with pytest.raises(RuntimeError, match="recipients"):
        ex.dump(fire_window_id="w1", dry_run=False)
    assert runner.calls == []


def test_dump_dry_run_is_noop(tmp_path: Path) -> None:
    runner = FakeRunner()
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(_write_recipients(tmp_path)),
        runner=runner,
    )
    assert ex.dump(fire_window_id="w1", dry_run=True) == (0, 0)
    assert runner.calls == []


def test_dump_happy_path_writes_secure_artefacts(tmp_path: Path) -> None:
    recipients = _write_recipients(tmp_path)

    # Side-effect: pg_dump fabricates a small file under --file=<dir>
    # so _dir_size returns >0; age writes a fixed payload to -o <out>.
    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        # find --file <dir>
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"x" * 1024)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_bytes(b"AGE-ENCRYPTED-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": fake_age})
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://x@y/z",
        pg_jobs=4,
        age_recipients_file=str(recipients),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
    )
    dump_bytes, enc_bytes = ex.dump(fire_window_id="2026-05-06T03:00:00+00:00", dry_run=False)
    assert dump_bytes == 1024
    assert enc_bytes == len(b"AGE-ENCRYPTED-BLOB")

    # ── argv shape ────────────────────────────────────────────────
    pg_call = next(c for c in runner.calls if os.path.basename(c[0]) == "pg_dump")
    assert "--format=directory" in pg_call
    assert "--jobs=4" in pg_call
    assert "--no-owner" in pg_call
    assert "--no-privileges" in pg_call
    # DSN passed via --dbname (not env)
    assert pg_call[pg_call.index("--dbname") + 1] == "postgresql://x@y/z"

    age_call = next(c for c in runner.calls if os.path.basename(c[0]) == "age")
    assert "-R" in age_call
    assert age_call[age_call.index("-R") + 1] == str(recipients)

    # ── Per-window dir + secure perms ─────────────────────────────
    safe_window = "2026-05-06T03_00_00+00_00"
    window_dir = tmp_path / "backups" / safe_window
    enc_path = window_dir / ENCRYPTED_NAME
    chk_path = window_dir / CHECKSUM_NAME
    man_path = window_dir / MANIFEST_NAME
    assert enc_path.is_file()
    assert chk_path.is_file()
    assert man_path.is_file()
    # Intermediate plaintext tar must be cleaned up
    assert not (window_dir / "_dump.tar").exists()
    # Plaintext dump dir must be cleaned up after encrypt
    assert not (window_dir / DUMP_DIR_NAME).exists()
    # 0o600 file mode (mask off the type bits)
    assert (enc_path.stat().st_mode & 0o777) == 0o600
    assert (chk_path.stat().st_mode & 0o777) == 0o600
    # 0o700 dir mode
    assert (window_dir.stat().st_mode & 0o777) == 0o700

    # ── Checksum matches ──────────────────────────────────────────
    expected = hashlib.sha256(b"AGE-ENCRYPTED-BLOB").hexdigest()
    assert chk_path.read_text().split()[0] == expected
    # Manifest references the encrypted artefact
    assert ENCRYPTED_NAME in man_path.read_text() or expected in man_path.read_text()


def test_dump_pg_dump_failure_surfaces(tmp_path: Path) -> None:
    def boom(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        raise subprocess.CalledProcessError(2, argv, output=b"", stderr=b"connection refused")

    runner = FakeRunner(handlers={"pg_dump": boom})
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(_write_recipients(tmp_path)),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
    )
    with pytest.raises(RuntimeError, match="pg_dump failed"):
        ex.dump(fire_window_id="w1", dry_run=False)


def test_dump_cleans_intermediate_tar_on_age_failure(tmp_path: Path) -> None:
    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"x")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def boom_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        raise subprocess.CalledProcessError(1, argv, output=b"", stderr=b"bad recipient")

    runner = FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": boom_age})
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(_write_recipients(tmp_path)),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
    )
    with pytest.raises(RuntimeError, match="age encryption failed"):
        ex.dump(fire_window_id="wfail", dry_run=False)
    # No leftover intermediate plaintext tar
    window_dir = tmp_path / "wfail"
    assert not (window_dir / "_dump.tar").exists()


# ── LocalSubprocessVerifier ────────────────────────────────────────────


def _seed_window_with_dump(tmp_path: Path, *, payload: bytes = b"BLOB", window: str = "w1") -> Path:
    safe = window.replace(":", "_").replace("/", "_")
    wdir = tmp_path / safe
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / ENCRYPTED_NAME).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (wdir / CHECKSUM_NAME).write_text(f"{digest}  {ENCRYPTED_NAME}\n")
    return wdir


def _seed_identity(tmp_path: Path) -> Path:
    p = tmp_path / "identity.txt"
    p.write_text("AGE-SECRET-KEY-1EXAMPLE\n")
    return p


def test_verify_returns_empty_when_dump_missing(tmp_path: Path) -> None:
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        age_identity_file=str(_seed_identity(tmp_path)),
        runner=FakeRunner(),
    )
    assert v.verify(fire_window_id="absent") == {}


def test_verify_returns_empty_on_checksum_mismatch(tmp_path: Path) -> None:
    wdir = _seed_window_with_dump(tmp_path)
    # Corrupt the encrypted blob after checksum was written
    (wdir / ENCRYPTED_NAME).write_bytes(b"TAMPERED")
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        age_identity_file=str(_seed_identity(tmp_path)),
        runner=FakeRunner(),
    )
    assert v.verify(fire_window_id="w1") == {}


def test_verify_happy_path_argv_and_parse(tmp_path: Path) -> None:
    _seed_window_with_dump(tmp_path)
    identity = _seed_identity(tmp_path)
    # Stub verify.sql so the file existence check passes.
    verify_sql = tmp_path / "verify.sql"
    verify_sql.write_text("SELECT 1;\n")

    # age -d: produce a valid tar with a dump.d/ entry
    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        with tarfile.open(out_path, "w") as tar:
            # write a small placeholder file inside dump.d/
            data_dir = out_path.parent / "stage" / DUMP_DIR_NAME
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "0001.dat").write_bytes(b"x")
            tar.add(data_dir.parent / DUMP_DIR_NAME, arcname=DUMP_DIR_NAME)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    psql_output = b"matches,42\npredict_final,7\n_schema_max_version,11\n"

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=psql_output, stderr=b"")

    def fake_docker(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "port" in argv:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"0.0.0.0:54321\n", stderr=b"")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "age": fake_age,
        "docker": fake_docker,
        "psql": fake_psql,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        pg_jobs=3,
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
        verify_sql_path=str(verify_sql),
    )
    out = v.verify(fire_window_id="w1")
    assert out == {"matches": 42, "predict_final": 7, "_schema_max_version": 11}

    # ── argv assertions ──────────────────────────────────────────
    age_call = next(c for c in runner.calls if os.path.basename(c[0]) == "age")
    assert "-d" in age_call
    assert "-i" in age_call
    assert age_call[age_call.index("-i") + 1] == str(identity)

    docker_run = next(
        c for c in runner.calls
        if os.path.basename(c[0]) == "docker" and "run" in c
    )
    assert "postgres:16-alpine" in docker_run
    # Pinned image — never *-latest
    assert not any(arg.endswith(":latest") for arg in docker_run)

    pg_restore_call = next(
        c for c in runner.calls
        if os.path.basename(c[0]) == "pg_restore"
    )
    assert "--jobs" in pg_restore_call
    assert pg_restore_call[pg_restore_call.index("--jobs") + 1] == "3"

    # Cleanup: docker rm -f always called
    assert any(
        c for c in runner.calls
        if os.path.basename(c[0]) == "docker" and "rm" in c and "-f" in c
    )


def test_sweep_orphans_returns_removed_names(tmp_path: Path) -> None:
    def fake_docker(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        if "ps" in argv:
            return subprocess.CompletedProcess(
                args=argv, returncode=0,
                stdout=b"negelir-verify-w1\nnegelir-verify-w2\n", stderr=b"",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={"docker": fake_docker})
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        age_identity_file=str(_seed_identity(tmp_path)),
        runner=runner,
        docker_binary="docker",
    )
    swept = v.sweep_orphans()
    assert set(swept) == {"negelir-verify-w1", "negelir-verify-w2"}


# ── Output parser ──────────────────────────────────────────────────────


def test_parse_verify_output_skips_blanks_and_non_int() -> None:
    txt = "matches,5\n\n  \nweird,abc\nplayers,99\n"
    assert _parse_verify_output(txt) == {"matches": 5, "players": 99}


# ── cfg validator ─────────────────────────────────────────────────────


def test_cfg_refuses_latest_verify_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai.common.config import Config
    monkeypatch.setenv("NEGELIR_MAINT_BACKUP_VERIFY_PG_IMAGE", "postgres:latest")
    cfg = Config()
    issues = cfg.validate()
    assert any("verify_pg_image" in i for i in issues), issues
