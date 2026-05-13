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
    DUMP_FILE_NAME,
    ENCRYPTED_NAME,
    MANIFEST_NAME,
    QUARANTINE_META_NAME,
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
    # ``-Z 9`` (max compression) is part of the §8.3 binding contract.
    assert "--compress=9" in pg_call
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


def test_dump_single_job_omits_jobs_flag(tmp_path: Path) -> None:
    """Format-jobs invariant: pg_jobs<=1 → ``-Fc`` (custom) + no ``--jobs``.

    pg_dump is single-threaded by default; ``-Fc`` is single-file and
    cannot parallelise. The §8.3 binding contract requires the agent
    to switch to ``--format=custom`` writing to ``negelir.dump`` when
    ``pg_jobs <= 1`` (one file per backup is operationally easier to
    ship around than a directory tree). Passing ``--jobs=1`` would
    additionally confuse audit-log readers into thinking parallel
    mode was attempted.
    """
    recipients = _write_recipients(tmp_path)

    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("--file") + 1])
        # ``-Fc`` writes to a file, not a directory. The fake mirrors
        # pg_dump's behaviour so the executor's post-dump fsync /
        # stat() succeeds.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"PGCOPY-FAKE-CUSTOM-DUMP")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_bytes(b"AGE-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": fake_age})
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://x@y/z",
        pg_jobs=1,
        age_recipients_file=str(recipients),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
    )
    ex.dump(fire_window_id="single", dry_run=False)
    pg_call = next(c for c in runner.calls if os.path.basename(c[0]) == "pg_dump")
    assert not any(a.startswith("--jobs=") for a in pg_call), (
        "pg_jobs<=1 must NOT pass --jobs (single-threaded default)"
    )
    # §8.3 binding: ``--format=custom`` (single-file) when pg_jobs<=1.
    assert "--format=custom" in pg_call
    assert "--format=directory" not in pg_call
    # ``--file`` points at the single-file artefact, not a directory.
    file_arg = pg_call[pg_call.index("--file") + 1]
    assert file_arg.endswith(DUMP_FILE_NAME), (
        f"-Fc must write to {DUMP_FILE_NAME}, got {file_arg}"
    )
    # --compress=9 still emitted regardless of jobs count.
    assert "--compress=9" in pg_call

    # Manifest records the format so operator+verifier can reason about it.
    window_dir = tmp_path / "backups" / "single"
    manifest = (window_dir / MANIFEST_NAME).read_text()
    assert '"format":"custom"' in manifest
    # Intermediate single-file dump artefact is cleaned up after encrypt.
    assert not (window_dir / DUMP_FILE_NAME).exists()
    assert not (window_dir / DUMP_DIR_NAME).exists()


def test_dump_custom_format_roundtrips_through_tar(tmp_path: Path) -> None:
    """§8.3 binding round-trip: encrypted blob from ``-Fc`` mode tars
    a single ``negelir.dump`` file (not a directory). Untarring the
    intermediate plaintext tar must yield exactly that one file with
    the original payload bytes — this is what the verifier extracts
    before invoking ``pg_restore``.
    """
    recipients = _write_recipients(tmp_path)
    payload = b"PGCOPY-FAKE-CUSTOM-DUMP-\x00\xff" * 64
    captured_tar: dict[str, bytes] = {}

    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("--file") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        # Snapshot the plaintext tar bytes before age (and the
        # executor's ``finally`` block) deletes them.
        tar_in = Path(argv[-1])
        captured_tar["bytes"] = tar_in.read_bytes()
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_bytes(b"AGE-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": fake_age})
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://x@y/z",
        pg_jobs=1,
        age_recipients_file=str(recipients),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
    )
    ex.dump(fire_window_id="rt", dry_run=False)

    # Tar must contain exactly one entry, named ``negelir.dump``, with
    # the original payload — this is what the verifier untars.
    import io
    tar_bytes = captured_tar["bytes"]
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        members = tar.getmembers()
        assert len(members) == 1
        assert members[0].name == DUMP_FILE_NAME
        extracted = tar.extractfile(members[0])
        assert extracted is not None
        assert extracted.read() == payload


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


def test_dump_writes_quarantine_meta_csv_outside_encrypted_blob(tmp_path: Path) -> None:
    """§8.3 binding: PII-aware sanitized projection of ``quarantine_samples``.

    Asserts the §8.3 restore DoD contract:

    * ``--exclude-table-data=quarantine_samples`` is in the ``pg_dump``
      argv (raw bytes never enter the encrypted dump).
    * A companion ``negelir.quarantine_meta.csv`` file is written
      ALONGSIDE the encrypted dump (not inside the encrypted tar — it
      is operator-only forensic evidence, not a ``pg_restore`` input).
    * The CSV is created via ``psql --csv -c "<projection SQL>"`` and
      the row count in the CSV matches the row count psql returned
      (this is the post-restore semantic guarantee: row count would
      have been included pre-erasure, post-restore the live table is
      empty by design).
    * The CSV is mode 0o600 (sensitive forensic metadata).
    """
    recipients = _write_recipients(tmp_path)

    # Three quarantine rows in the projection — header + 3 data rows.
    psql_csv = (
        b"quarantine_id,source,verdict,reasons,bytes_sha256,detected_at,erased_at,pii_redacted\n"
        b"q1,scrape,quarantine,oversized,"
        + b"a" * 64 + b",2026-05-13T03:00:00+00:00,,f\n"
        b"q2,qa,quarantine,bad_utf8|too_short,"
        + b"b" * 64 + b",2026-05-13T03:00:01+00:00,2026-05-13T04:00:00+00:00,t\n"
        b"q3,scrape,quarantine,blocklisted,"
        + b"c" * 64 + b",2026-05-13T03:00:02+00:00,,f\n"
    )
    expected_data_rows = 3

    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"x")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=psql_csv, stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_bytes(b"AGE-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={
        "pg_dump": fake_pg_dump,
        "psql": fake_psql,
        "age": fake_age,
    })
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://x@y/z",
        pg_jobs=2,
        age_recipients_file=str(recipients),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
        psql_binary="psql",
    )
    ex.dump(fire_window_id="meta", dry_run=False)

    # ── pg_dump excludes quarantine row data ──────────────────────
    pg_call = next(c for c in runner.calls if os.path.basename(c[0]) == "pg_dump")
    assert "--exclude-table-data=quarantine_samples" in pg_call, (
        "raw quarantine bytes must NEVER enter the encrypted dump"
    )

    # ── psql invoked with --csv against the configured DSN ────────
    psql_call = next(c for c in runner.calls if os.path.basename(c[0]) == "psql")
    assert "--csv" in psql_call
    assert "--no-psqlrc" in psql_call
    assert psql_call[psql_call.index("--dbname") + 1] == "postgresql://x@y/z"
    sql_idx = psql_call.index("-c") + 1
    sql = psql_call[sql_idx]
    assert "FROM quarantine_samples" in sql
    assert "ORDER BY detected_at" in sql
    # Sanitized: no raw_bytes, no client_id, no ip in the projection
    assert "raw_bytes" not in sql
    assert "client_id" not in sql
    assert " ip " not in sql and " ip," not in sql

    # ── Companion CSV exists alongside (NOT inside) the encrypted blob
    window_dir = tmp_path / "backups" / "meta"
    meta_path = window_dir / QUARANTINE_META_NAME
    enc_path = window_dir / ENCRYPTED_NAME
    assert meta_path.is_file(), "negelir.quarantine_meta.csv must exist"
    assert enc_path.is_file()
    # 0o600 — sensitive forensic metadata
    assert (meta_path.stat().st_mode & 0o777) == 0o600

    # ── CSV is parsable + row count matches psql output ───────────
    import csv as _csv
    with meta_path.open("r", encoding="utf-8", newline="") as fh:
        reader = _csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == expected_data_rows, (
        f"CSV row count {len(rows)} must match psql data-row count "
        f"{expected_data_rows} (DoD: pre-erasure projection preserved)"
    )
    # Sanity: header columns include the sanitized projection fields
    assert reader.fieldnames is not None
    assert "quarantine_id" in reader.fieldnames
    assert "bytes_sha256" in reader.fieldnames
    assert "raw_bytes" not in reader.fieldnames


def test_dump_disabled_quarantine_exclude_skips_meta_csv(tmp_path: Path) -> None:
    """Symmetry: when exclude_quarantine_data=False, no projection CSV
    is written (quarantine rows ride inside the encrypted dump
    normally; the forensic companion is unnecessary).
    """
    recipients = _write_recipients(tmp_path)

    def fake_pg_dump(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_dir = Path(argv[argv.index("--file") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0001.dat").write_bytes(b"x")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        out_path.write_bytes(b"AGE-BLOB")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={"pg_dump": fake_pg_dump, "age": fake_age})
    ex = LocalPgDumpExecutor(
        backup_dir=str(tmp_path / "backups"),
        pg_dsn="postgresql://x@y/z",
        age_recipients_file=str(recipients),
        runner=runner,
        pg_dump_binary="pg_dump",
        age_binary="age",
        exclude_quarantine_data=False,
    )
    ex.dump(fire_window_id="nometa", dry_run=False)

    # No psql call, no projection CSV
    assert not any(os.path.basename(c[0]) == "psql" for c in runner.calls)
    pg_call = next(c for c in runner.calls if os.path.basename(c[0]) == "pg_dump")
    assert "--exclude-table-data=quarantine_samples" not in pg_call
    window_dir = tmp_path / "backups" / "nometa"
    assert not (window_dir / QUARANTINE_META_NAME).exists()


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


# ── toc_only escape hatch (ROADMAP §8.3) ───────────────────────────────


def test_verify_toc_only_runs_pg_restore_list_and_skips_docker(
    tmp_path: Path,
) -> None:
    """`mode='toc_only'` decrypts + untars + runs `pg_restore --list`
    only. No docker container, no psql. Returns the TOC-entry count
    sentinel on success."""
    _seed_window_with_dump(tmp_path)
    identity = _seed_identity(tmp_path)

    def fake_age(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        out_path = Path(argv[argv.index("-o") + 1])
        with tarfile.open(out_path, "w") as tar:
            data_dir = out_path.parent / "stage" / DUMP_DIR_NAME
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "0001.dat").write_bytes(b"x")
            tar.add(data_dir.parent / DUMP_DIR_NAME, arcname=DUMP_DIR_NAME)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    # Realistic `pg_restore --list` output: comments + 3 TOC entries.
    toc_stdout = (
        b"; Archive created at 2025-01-01\n"
        b";\n"
        b"1; 2615 16386 SCHEMA - public postgres\n"
        b"2; 1259 16387 TABLE public matches postgres\n"
        b"3; 1259 16388 TABLE public predict_final postgres\n"
    )

    def fake_pg_restore(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        assert "--list" in argv, "toc_only must invoke pg_restore --list"
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=toc_stdout, stderr=b"")

    runner = FakeRunner(handlers={
        "age": fake_age,
        "pg_restore": fake_pg_restore,
    })
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        age_identity_file=str(identity),
        runner=runner,
        docker_binary="docker",
        age_binary="age",
        pg_restore_binary="pg_restore",
        psql_binary="psql",
    )
    out = v.verify(fire_window_id="w1", mode="toc_only")
    assert out == {"_toc_only": 1, "_toc_entries": 3}
    # No docker / psql calls in toc_only mode.
    assert not any(
        os.path.basename(c[0]) in ("docker", "psql") for c in runner.calls
    )


def test_verify_toc_only_returns_empty_on_checksum_mismatch(
    tmp_path: Path,
) -> None:
    """Silent-corruption gate must still trip in toc_only mode \u2014 it
    is the whole point of running verify at all."""
    wdir = _seed_window_with_dump(tmp_path)
    (wdir / ENCRYPTED_NAME).write_bytes(b"TAMPERED")
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        age_identity_file=str(_seed_identity(tmp_path)),
        runner=FakeRunner(),
    )
    assert v.verify(fire_window_id="w1", mode="toc_only") == {}


def test_verify_rejects_unknown_mode(tmp_path: Path) -> None:
    """Unknown modes return empty (Protocol contract: agent reads as
    `verify_failed`); implementations must not branch on values
    outside the closed enum."""
    _seed_window_with_dump(tmp_path)
    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        age_identity_file=str(_seed_identity(tmp_path)),
        runner=FakeRunner(),
    )
    assert v.verify(fire_window_id="w1", mode="row_count_only") == {}


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
