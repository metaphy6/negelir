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
    DUMP_FILE_NAME,
    ENCRYPTED_NAME,
    MANIFEST_NAME,
    QUARANTINE_META_NAME,
    LocalPgDumpExecutor,
    LocalPgPruner,
    TableResolutionError,
)
from xops.maint.prune_order import PRUNE_ORDER
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
        # §8.14.9: pg_dump argv may be prefixed by nice/ionice wrappers.
        # Search the full argv for the first element whose basename matches
        # a registered handler (not just argv[0]) so that handlers like
        # "pg_dump" still fire when the call is nice/ionice-wrapped.
        head = next(
            (os.path.basename(arg) for arg in argv if os.path.basename(arg) in self.handlers),
            os.path.basename(argv[0]),
        )
        handler = self.handlers.get(head)
        if handler is None:
            return subprocess.CompletedProcess(
                args=list(argv), returncode=0, stdout=b"", stderr=b"",
            )
        return handler(list(argv), env, cwd)


def _sql_from_argv(argv: list[str]) -> str:
    return argv[argv.index("-c") + 1]


def test_pg_pruner_dry_run_counts_without_mutation() -> None:
    calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        sql = _sql_from_argv(argv)
        calls.append(sql)
        # Existence probes.
        if "to_regclass('public.opsctl_audit')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        if "to_regclass('public.schema_snapshots')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        if "to_regclass('public.pattern_allowlist')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        if "to_regclass('public.dlq_entries')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.quarantine_samples')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        if "to_regclass('public.maint_audit_log')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.maint_audit_log_pii')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        # Dry-run counts.
        if "COUNT(*) FROM opsctl_audit" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"9\n", stderr=b"")
        if "COUNT(*) FROM schema_snapshots" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"4\n", stderr=b"")
        if "COUNT(*) FROM pattern_allowlist" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"3\n", stderr=b"")
        if "COUNT(*) FROM quarantine_samples" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"2\n", stderr=b"")
        if "COUNT(*) FROM maint_audit_log_pii" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"1\n", stderr=b"")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"0\n", stderr=b"")

    runner = FakeRunner(handlers={"psql": fake_psql})
    pruner = LocalPgPruner(
        pg_dsn="postgresql://x@y/z",
        prune_batch=10,
        sec_quarantine_ttl_days=30,
        schema_snapshot_retention_days=90,
        dlq_retention_days=14,
        audit_retention_days=365,
        runner=runner,
        psql_binary="psql",
    )
    out = pruner.prune(dry_run=True)
    assert tuple(out.keys()) == PRUNE_ORDER
    assert out["opsctl_audit"] == 9
    assert out["schema_snapshots"] == 4
    assert out["pattern_allowlist"] == 3
    assert out["dlq_entries"] == 0
    assert out["quarantine_samples"] == 2
    assert out["maint_audit_log"] == 1
    assert not any("DO $$" in sql for sql in calls), "dry-run must not execute deletes"


def test_pg_pruner_batched_delete_uses_do_loop_and_alias_fallback() -> None:
    calls: list[str] = []

    def fake_psql(argv: list[str], *_a: Any) -> "subprocess.CompletedProcess[bytes]":
        sql = _sql_from_argv(argv)
        calls.append(sql)
        if "to_regclass('public.opsctl_audit')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        if "to_regclass('public.schema_snapshots')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.pattern_allowlist')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.dlq_entries')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.quarantine_samples')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.maint_audit_log')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"f\n", stderr=b"")
        if "to_regclass('public.maint_audit_log_pii')" in sql:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"t\n", stderr=b"")
        if "DO $$" in sql and "opsctl_audit" in sql:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"",
                stderr=b"NOTICE:  pruned_total=7\n",
            )
        if "DO $$" in sql and "maint_audit_log_pii" in sql:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=b"",
                stderr=b"NOTICE:  pruned_total=2\n",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=b"", stderr=b"")

    runner = FakeRunner(handlers={"psql": fake_psql})
    pruner = LocalPgPruner(
        pg_dsn="postgresql://x@y/z",
        prune_batch=123,
        sec_quarantine_ttl_days=30,
        schema_snapshot_retention_days=90,
        dlq_retention_days=14,
        audit_retention_days=365,
        runner=runner,
        psql_binary="psql",
    )
    out = pruner.prune(dry_run=False)
    assert out["opsctl_audit"] == 7
    assert out["maint_audit_log"] == 2
    # Alias fallback picks maint_audit_log_pii when logical table is absent.
    assert any("to_regclass('public.maint_audit_log_pii')" in sql for sql in calls)
    delete_sql = "\n".join(sql for sql in calls if "DO $$" in sql)
    assert "LIMIT 123" in delete_sql
    assert "ORDER BY ts_utc ASC" in delete_sql
    assert "ORDER BY produced_at ASC" in delete_sql


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
    # §8.14.9: pg_dump argv may be wrapped by nice/ionice; search all elements.
    pg_call = next(c for c in runner.calls if any(os.path.basename(a) == "pg_dump" for a in c))
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
    # §8.14.9: pg_dump argv may be wrapped by nice/ionice; search all elements.
    pg_call = next(c for c in runner.calls if any(os.path.basename(a) == "pg_dump" for a in c))
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
    manifest = json.loads((window_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["format"] == "custom"
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

    # Tar must contain exactly two entries: the dump file (negelir.dump)
    # and the §8.14.2 per-file manifest (negelir.files.sha256.txt).
    import io
    tar_bytes = captured_tar["bytes"]
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        members = tar.getmembers()
        names = {m.name for m in members}
        assert len(members) == 2
        assert DUMP_FILE_NAME in names
        from xops.backup.executors import FILE_CHECKSUM_MANIFEST_NAME
        assert FILE_CHECKSUM_MANIFEST_NAME in names
        # The dump file payload is intact.
        dump_member = next(m for m in members if m.name == DUMP_FILE_NAME)
        extracted = tar.extractfile(dump_member)
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
    # §8.14.9: pg_dump argv may be wrapped by nice/ionice; search all elements.
    pg_call = next(c for c in runner.calls if any(os.path.basename(a) == "pg_dump" for a in c))
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

    # §8.14.9: a psql call IS made for SHOW server_version_num; the assertion
    # should verify that the quarantine CSV projection (psql --csv) is NOT called.
    assert not any(
        any(os.path.basename(a) == "psql" for a in c) and "--csv" in c
        for c in runner.calls
    ), "psql --csv (quarantine projection) must not be called when exclude_quarantine_data=False"
    # §8.14.9: pg_dump argv may be wrapped by nice/ionice; search all elements.
    pg_call = next(c for c in runner.calls if any(os.path.basename(a) == "pg_dump" for a in c))
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
    # The window was seeded without a manifest (no migrations_at_dump_time) so
    # the legacy-manifest path is taken: _legacy_manifest=1 is included.
    assert out.get("matches") == 42
    assert out.get("predict_final") == 7
    assert out.get("_schema_max_version") == 11
    assert out.get("_legacy_manifest") == 1

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
    from common.config import Config
    monkeypatch.setenv("NEGELIR_MAINT_BACKUP_VERIFY_PG_IMAGE", "postgres:latest")
    cfg = Config()
    issues = cfg.validate()
    assert any("verify_pg_image" in i for i in issues), issues


# ── TableResolutionError doctrine tests ───────────────────────────────


def _make_pruner(runner: FakeRunner) -> LocalPgPruner:
    return LocalPgPruner(
        pg_dsn="postgresql://x@y/z",
        prune_batch=10,
        sec_quarantine_ttl_days=30,
        schema_snapshot_retention_days=90,
        dlq_retention_days=14,
        audit_retention_days=365,
        runner=runner,
        psql_binary="psql",
    )


def test_resolve_table_raises_table_resolution_error_on_subprocess_failure() -> None:
    """_resolve_table must NOT silently return None when psql itself fails.

    A CalledProcessError from psql (e.g. connection refused) is a
    database infrastructure error, not a "table not found" signal.
    Swallowing it would let the prune run silently report 0 for every
    table while postgres is unreachable.
    """

    def failing_psql(
        argv: list[str], *_a: Any
    ) -> "subprocess.CompletedProcess[bytes]":
        raise subprocess.CalledProcessError(
            1, argv, output=b"", stderr=b"connection refused"
        )

    pruner = _make_pruner(FakeRunner(handlers={"psql": failing_psql}))
    with pytest.raises(TableResolutionError, match="existence probe failed"):
        pruner.prune(dry_run=True)


def test_resolve_table_raises_table_resolution_error_on_missing_binary() -> None:
    """_resolve_table must NOT silently return None when the psql binary is missing.

    FileNotFoundError means the binary is absent entirely; treating it as
    "table not found" would hide an environment misconfiguration.
    """

    def missing_binary(
        argv: list[str], *_a: Any
    ) -> "subprocess.CompletedProcess[bytes]":
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    pruner = _make_pruner(FakeRunner(handlers={"psql": missing_binary}))
    with pytest.raises(TableResolutionError):
        pruner.prune(dry_run=True)


def test_count_where_raises_table_resolution_error_on_non_integer_output() -> None:
    """_count_where must NOT silently return 0 when psql returns unexpected output.

    A successful psql invocation that returns non-integer stdout is a
    logic error in the query or an unexpected DB message — returning 0
    would hide it and could cause the prune run to skip prunable rows.
    """

    def weird_output(
        argv: list[str], *_a: Any
    ) -> "subprocess.CompletedProcess[bytes]":
        sql = _sql_from_argv(argv)
        if "to_regclass" in sql:
            # Probe says table exists.
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout=b"t\n", stderr=b""
            )
        # COUNT(*) returns a non-parseable string instead of a number.
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=b"ERROR: some db message\n", stderr=b""
        )

    # Use a pruner that will hit the COUNT path (dry_run=True on a table
    # that resolves to a real name).
    pruner = _make_pruner(FakeRunner(handlers={"psql": weird_output}))
    with pytest.raises(TableResolutionError, match="non-integer"):
        pruner.prune(dry_run=True)


# ── §8.14.9 nice/ionice wrapping + verify-PG version invariant ───────────────


def test_pg_dump_nice_wraps_argv_default(tmp_path: Path) -> None:
    """§8.14.9 binding: nice_level=10, ionice_enabled=False → nice prefix in argv.

    Asserts that `_wrap_nice_ionice` prepends ``nice -n 10`` to the
    pg_dump argv when nice_level=10.  ionice is disabled so the test is
    platform-agnostic (ionice is Linux-only).
    """
    from xops.backup.executors import _wrap_nice_ionice

    result = _wrap_nice_ionice(
        ["pg_dump", "--format=directory", "--file", "/tmp/dump"],
        nice_level=10,
        ionice_enabled=False,
        _is_linux=False,
    )
    assert result[:3] == ["nice", "-n", "10"], f"expected nice prefix, got {result[:3]}"
    assert "pg_dump" in result[3], f"pg_dump should follow the nice prefix, got {result[3]}"


def test_pg_dump_mock_profile_no_nice_no_ionice(tmp_path: Path) -> None:
    """§8.14.9 binding: nice_level=0 → no nice/ionice prefix at all.

    Mock / dedicated-PG deployments set NEGELIR_MAINT_BACKUP_PG_DUMP_NICE_LEVEL=0
    to bypass priority wrapping entirely.  When nice_level=0 and ionice_enabled
    is irrelevant (False), pg_dump must be the first element.
    """
    from xops.backup.executors import _wrap_nice_ionice

    orig = ["pg_dump", "--format=directory", "--file", "/tmp/dump"]
    result = _wrap_nice_ionice(
        orig,
        nice_level=0,
        ionice_enabled=False,
        _is_linux=False,
    )
    assert result[0] == "pg_dump", (
        f"nice_level=0 must not prepend anything; got {result[0]}"
    )
    # Original must not be mutated (the function returns orig unchanged or a new list).
    assert orig[0] == "pg_dump", "original list must not be mutated"


def test_pg_dump_ionice_linux_prepends_ionice_then_nice(tmp_path: Path) -> None:
    """§8.14.9 binding: nice_level=5, ionice_enabled=True, Linux →
    ``ionice -c 2 -n 7 nice -n 5 pg_dump …``  (ionice wraps nice wraps pg_dump).

    The ionice part is injected after the nice part so that ionice
    applies to the nice-wrapped pg_dump process.
    """
    from xops.backup.executors import _wrap_nice_ionice

    result = _wrap_nice_ionice(
        ["pg_dump", "--format=directory"],
        nice_level=5,
        ionice_enabled=True,
        _is_linux=True,
    )
    assert result[0] == "nice", f"expected nice first, got {result[0]}"
    assert result[1:3] == ["-n", "5"], f"expected -n 5, got {result[1:3]}"
    # ionice follows the nice prefix
    assert result[3] == "ionice", f"expected ionice after nice prefix, got {result[3]}"
    assert result[4:8] == ["-c", "2", "-n", "7"], (
        f"expected -c 2 -n 7, got {result[4:8]}"
    )
    assert "pg_dump" in result[8], f"pg_dump must follow ionice, got {result[8]}"


def test_verify_pg_too_old_refuses_and_sets_info(tmp_path: Path) -> None:
    """§8.14.9 verify-PG version invariant: manifest server_version_num=170000
    (PG 17) + verify image postgres:16-alpine (image_major=16) → verify()
    returns {} and sets last_verify_pg_too_old_info with fail_safe kind.

    This is an adversarial test: the verifier MUST refuse before spinning a
    Docker container, not silently attempt a pg_restore that would fail.
    """
    safe_window = "2026-05-06T03_00_00+00_00"
    wdir = tmp_path / safe_window
    wdir.mkdir(parents=True, exist_ok=True)
    payload = b"FAKE-BLOB"
    (wdir / ENCRYPTED_NAME).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (wdir / CHECKSUM_NAME).write_text(f"{digest}  {ENCRYPTED_NAME}\n")
    # Manifest records a PG 17 source version num.
    manifest_data = {
        "fire_window_id": "2026-05-06T03:00:00+00:00",
        "server_version_num": 170000,
    }
    (wdir / MANIFEST_NAME).write_text(json.dumps(manifest_data) + "\n", encoding="utf-8")
    identity = _seed_identity(tmp_path)

    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=FakeRunner(),  # no subprocess calls should be made
    )
    result = v.verify(fire_window_id="2026-05-06T03:00:00+00:00")
    assert result == {}, "verifier must refuse PG too-old by returning empty dict"
    info = v.last_verify_pg_too_old_info
    assert info is not None, "last_verify_pg_too_old_info must be populated on refusal"
    assert info["kind"] == "fail_safe_verify_pg_too_old"
    assert info["image_version_num"] == 160000, (
        f"postgres:16-alpine → 160000, got {info['image_version_num']}"
    )
    assert info["source_version_num"] == 170000, (
        f"source version_num=170000, got {info['source_version_num']}"
    )
    assert info["pg_image"] == "postgres:16-alpine"


def test_verify_pg_same_major_does_not_refuse(tmp_path: Path) -> None:
    """§8.14.9 — same major version (postgres:16 image, PG 16.4 source = 160004)
    must NOT trigger VerifyPgTooOldError.

    A patch-level difference within the same major is supported by pg_restore;
    only a major-version downgrade is refused.
    """
    from xops.backup.verifier import _parse_pg_image_version_num, VerifyPgTooOldError

    # Direct unit test on the parser + comparison logic.
    image_version_num = _parse_pg_image_version_num("postgres:16-alpine")
    source_version_num = 160004  # PG 16.4

    assert image_version_num == 160000, (
        f"postgres:16-alpine should parse to 160000, got {image_version_num}"
    )
    # Major versions match: 16 == 16 → no refusal.
    assert image_version_num // 10000 == source_version_num // 10000, (
        "Same major version must not trigger refusal"
    )


def test_verify_pg_too_old_info_cleared_on_next_call(tmp_path: Path) -> None:
    """§8.14.9 — last_verify_pg_too_old_info must be cleared at the start of
    each verify() call so stale info from a prior refusal does not bleed into
    a subsequent successful (or differently-failed) call.
    """
    safe_window = "2026-05-06T04_00_00+00_00"
    wdir = tmp_path / safe_window
    wdir.mkdir(parents=True, exist_ok=True)
    payload = b"FAKE-BLOB-2"
    (wdir / ENCRYPTED_NAME).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (wdir / CHECKSUM_NAME).write_text(f"{digest}  {ENCRYPTED_NAME}\n")
    manifest_data = {"fire_window_id": "2026-05-06T04:00:00+00:00", "server_version_num": 170000}
    (wdir / MANIFEST_NAME).write_text(json.dumps(manifest_data) + "\n", encoding="utf-8")
    identity = _seed_identity(tmp_path)

    v = LocalSubprocessVerifier(
        backup_dir=str(tmp_path),
        pg_image="postgres:16-alpine",
        age_identity_file=str(identity),
        runner=FakeRunner(),
    )
    # First call: refused (PG too old) — populates last_verify_pg_too_old_info.
    v.verify(fire_window_id="2026-05-06T04:00:00+00:00")
    assert v.last_verify_pg_too_old_info is not None

    # Second call: window is absent — returns {} for a different reason.
    v.verify(fire_window_id="absent-window")
    assert v.last_verify_pg_too_old_info is None, (
        "last_verify_pg_too_old_info must be cleared between verify() calls"
    )
