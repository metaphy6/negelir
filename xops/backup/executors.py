"""Phase 8 §8.3 — live ``DumpExecutor`` adapters (stdlib + subprocess).

This module provides the production driver for the
:class:`swarm.agents.maint.backup.DumpExecutor` Protocol. It wraps
``pg_dump`` (Fd directory format with parallel jobs) and ``age``
(symmetric / recipients-file encryption) behind a small,
unit-testable shape.

Doctrine respected:

* **Single-source config (Rule 1).** All tunables come from
  ``ai.common.config.cfg`` — DSN, jobs, target dir, recipients file.
  No magic strings, no hardcoded paths.
* **No fabricated production data (Rule 3).** A failed dump raises;
  the agent records ``backup_completed{outcome=dump_failed}`` and
  does NOT silently fall back to fake bytes.
* **0600 perms (§8.3 binding contract).** The output directory is
  created with ``0o700`` (umask scoped to the call), every file
  written under it gets ``0o600`` chmod after fsync. A SHA-256
  checksum is written next to the dump payload after fsync so a
  later integrity check can detect silent corruption.
* **English infra (Rule 6).** Log messages, error strings, audit
  fields are English; the payload (``fire_window_id``) is opaque.

The class is pure-construction (no I/O at import) and
DI-friendly: tests inject a fake ``runner`` to avoid spawning
real subprocesses.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Protocol, Sequence


_log = logging.getLogger("xops.backup.executors")


class TableResolutionError(RuntimeError):
    """Raised when a psql existence-probe or count query fails unexpectedly.

    This signals a database connectivity or binary error. Callers must NOT
    treat this as "table not found" — it means the probing infrastructure
    itself is broken and the prune run cannot proceed safely.
    """


# Filenames inside the per-fire-window directory. Pinned so the
# verifier + restore CLI can find them without an inventory probe.
DUMP_DIR_NAME: str = "dump.d"
# §8.3 binding: ``-Fc`` (custom) single-file dump filename, used when
# ``pg_jobs <= 1``. The format is selected by ``LocalPgDumpExecutor``
# at dump time; the verifier auto-detects which artefact is present
# inside the encrypted tar (file vs directory) and dispatches to
# ``pg_restore`` accordingly.
DUMP_FILE_NAME: str = "negelir.dump"
ENCRYPTED_NAME: str = "dump.tar.age"
CHECKSUM_NAME: str = "negelir.checksum.txt"
MANIFEST_NAME: str = "manifest.json"
# PII-aware sanitized projection of ``quarantine_samples`` (§8.3
# binding contract). Written alongside the encrypted dump as
# **operator-only forensic evidence** — it is NOT a ``pg_restore``
# input. After restore, ``quarantine_samples`` will be empty (schema
# present, no rows) by design; this CSV preserves the metadata trail
# (no raw bytes) so an operator can audit what was quarantined at
# backup time. Mode 0600, never auto-loaded.
QUARANTINE_META_NAME: str = "negelir.quarantine_meta.csv"
# Sanitized projection SQL — mirrors the actual ``quarantine_samples``
# schema (migration 007) minus ``raw_bytes`` and any direct PII
# identifiers (``client_id``, ``ip``). ``erased_at`` is included so
# the operator can distinguish post-erasure rows from live ones.
_QUARANTINE_META_SQL: str = (
    "SELECT quarantine_id, source, verdict, "
    "array_to_string(reasons, '|') AS reasons, "
    "bytes_sha256, detected_at, erased_at, pii_redacted "
    "FROM quarantine_samples "
    "ORDER BY detected_at"
)


class CommandRunner(Protocol):
    """DI surface for ``subprocess.run`` so tests can avoid spawning
    real ``pg_dump`` / ``age`` binaries.

    Implementations MUST raise :class:`subprocess.CalledProcessError`
    on non-zero exit codes (mirroring ``check=True`` semantics).
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess[bytes]":
        ...


def _default_runner(
    argv: Sequence[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> "subprocess.CompletedProcess[bytes]":
    """Default runner — ``subprocess.run(check=True, capture_output=True)``.

    Stderr is captured (binary) and surfaced through
    :class:`subprocess.CalledProcessError` so the agent can log a
    redacted failure note without leaking secrets via stderr to
    parent process stdio.
    """
    return subprocess.run(  # noqa: S603 — argv is composed from cfg + window id
        list(argv),
        env=dict(env) if env is not None else None,
        cwd=cwd,
        timeout=timeout,
        check=True,
        capture_output=True,
    )


def _ensure_secure_dir(path: Path) -> None:
    """Create ``path`` (and parents) with 0o700, even if existing.

    Defence-in-depth against an operator clearing the dir then
    re-creating it with a wider mode.
    """
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError as exc:  # pragma: no cover — chmod failure is rare
        _log.warning("chmod 0o700 on %s failed: %s", path, exc)


def _chmod_secure(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as exc:  # pragma: no cover
        _log.warning("chmod 0o600 on %s failed: %s", path, exc)


def _fsync_path(path: Path) -> None:
    """Open the file read-only just to fsync the bytes to disk."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LocalPgDumpExecutor:
    """``pg_dump -Fd`` + ``age`` recipients-file encryption.

    The dump runs into a per-fire-window subdirectory of
    ``cfg.maint_backup_dir`` (created 0o700). After a successful
    dump the directory tree is tarred, piped through ``age -R
    <recipients>`` to produce ``dump.tar.age`` (0o600), and a
    sibling ``negelir.checksum.txt`` records the SHA-256 of the
    encrypted blob (the post-fsync integrity probe per §8.3).

    Construction:

        LocalPgDumpExecutor(
            backup_dir=cfg.maint_backup_dir,
            pg_dsn=cfg.maint_backup_pg_dsn,
            pg_jobs=cfg.maint_backup_pg_jobs,
            age_recipients_file=cfg.maint_backup_age_recipients_file,
        )

    Tests inject ``runner=`` to avoid spawning real subprocesses.
    """

    backup_dir: str
    pg_dsn: str
    pg_jobs: int = 2
    age_recipients_file: str = ""
    runner: CommandRunner = field(default=_default_runner)
    # Optional override for ``age`` binary path (otherwise resolved
    # via ``shutil.which`` lazily on the first ``dump()`` call).
    age_binary: Optional[str] = None
    pg_dump_binary: Optional[str] = None
    psql_binary: Optional[str] = None
    # PII-aware policy (§8.3 binding contract). When true,
    # ``--exclude-table-data=quarantine_samples`` is appended to the
    # ``pg_dump`` argv so the raw bytes of quarantined samples never
    # land in the encrypted dump (right-to-erasure invariant). The
    # schema is still dumped — restore-verify can re-create the table
    # without rows.
    exclude_quarantine_data: bool = True

    def dump(self, *, fire_window_id: str, dry_run: bool) -> tuple[int, int]:
        """Run ``pg_dump`` then encrypt with ``age``.

        Returns ``(dump_bytes, encrypted_bytes)``. On ``dry_run=True``
        the call is a no-op that returns ``(0, 0)`` — the
        :class:`MaintBackupAgent` already short-circuits prune/verify
        in that mode, but the executor honours the flag defensively.
        """
        if dry_run:
            _log.info(
                "LocalPgDumpExecutor.dump dry_run=true window=%s",
                fire_window_id,
            )
            return (0, 0)

        if not self.pg_dsn:
            raise RuntimeError(
                "LocalPgDumpExecutor: cfg.maint_backup_pg_dsn is empty; "
                "refuse-to-start instead of producing a useless dump."
            )

        recipients = self.age_recipients_file
        if not recipients or not os.path.isfile(recipients):
            raise RuntimeError(
                f"LocalPgDumpExecutor: age recipients file "
                f"{recipients!r} missing or not readable; "
                f"refuse-to-start instead of writing plaintext."
            )

        root = Path(self.backup_dir)
        _ensure_secure_dir(root)
        # The fire_window_id can contain ':' (ISO timestamp) — sanitize
        # to a safe filename. We keep the original id in the manifest.
        safe_window = fire_window_id.replace(":", "_").replace("/", "_")
        window_dir = root / safe_window
        _ensure_secure_dir(window_dir)

        # ── pg_dump ────────────────────────────────────────────────────
        # Format-jobs invariant (§8.3 binding): ``--jobs > 1`` requires
        # ``-Fd`` (directory format). When ``pg_jobs <= 1`` we use
        # ``-Fc`` (custom, single-file) and drop the ``--jobs`` flag
        # entirely — pg_dump is single-threaded by default, ``-Fc``
        # cannot parallelise, and ``negelir.dump`` is operationally
        # easier to ship around than a directory tree (one file = one
        # checksum = one rsync). The downstream tar/age pipeline stays
        # uniform — we tar the single file (or directory) before
        # encrypting; the verifier auto-detects post-extract which one
        # is present and dispatches ``pg_restore`` accordingly.
        # ``-Z 9`` selects maximum gzip compression for the dump payload
        # — large prediction tables compress >10× and the CPU cost is
        # paid by the backup role, not the application connection pool.
        use_directory = int(self.pg_jobs) > 1
        if use_directory:
            dump_target: Path = window_dir / DUMP_DIR_NAME
            _ensure_secure_dir(dump_target)
            tar_arcname = DUMP_DIR_NAME
            format_arg = "--format=directory"
            format_label = "directory"
        else:
            dump_target = window_dir / DUMP_FILE_NAME
            tar_arcname = DUMP_FILE_NAME
            format_arg = "--format=custom"
            format_label = "custom"
        pg_dump = self.pg_dump_binary or shutil.which("pg_dump") or "pg_dump"
        argv = [
            pg_dump,
            format_arg,
            "--compress=9",
            "--no-owner",
            "--no-privileges",
            "--file", str(dump_target),
            "--dbname", self.pg_dsn,
        ]
        if use_directory:
            argv.insert(2, f"--jobs={int(self.pg_jobs)}")
        if self.exclude_quarantine_data:
            # PII-aware policy — schema is still dumped, only the row
            # data is excluded. Restore-verify gets an empty table.
            argv.append("--exclude-table-data=quarantine_samples")
        _log.info(
            "pg_dump window=%s argv=%s",
            fire_window_id, shlex.join(argv[:-1] + ["<dsn-redacted>"]),
        )
        try:
            self.runner(argv)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace")[:2048]
            raise RuntimeError(
                f"pg_dump failed (rc={exc.returncode}): {stderr.strip()}"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"pg_dump binary not found: {exc}") from exc

        if use_directory:
            dump_bytes = _dir_size(dump_target)
        else:
            try:
                _chmod_secure(dump_target)
                _fsync_path(dump_target)
                dump_bytes = dump_target.stat().st_size
            except OSError as exc:
                raise RuntimeError(
                    f"pg_dump produced no output file at {dump_target}: {exc}"
                ) from exc

        # ── PII-aware sanitized projection (§8.3 binding contract) ───
        # When ``--exclude-table-data=quarantine_samples`` was passed,
        # the encrypted dump will restore an empty table. We separately
        # write a forensic-evidence CSV (no raw bytes, no client_id,
        # no ip) so the operator can audit what was quarantined at
        # backup time. The CSV stays OUTSIDE the encrypted tar — it is
        # operator-only forensic evidence, not a ``pg_restore`` input.
        if self.exclude_quarantine_data:
            self._write_quarantine_meta_csv(window_dir)

        # ── tar + age encrypt ─────────────────────────────────────────
        encrypted_path = window_dir / ENCRYPTED_NAME
        tar_path = window_dir / "_dump.tar"
        try:
            with tarfile.open(tar_path, "w") as tar:
                tar.add(dump_target, arcname=tar_arcname)
            _chmod_secure(tar_path)
            _fsync_path(tar_path)

            age = self.age_binary or shutil.which("age") or "age"
            age_argv = [
                age,
                "-R", recipients,
                "-o", str(encrypted_path),
                str(tar_path),
            ]
            try:
                self.runner(age_argv)
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or b"").decode(errors="replace")[:2048]
                raise RuntimeError(
                    f"age encryption failed (rc={exc.returncode}): "
                    f"{stderr.strip()}"
                ) from exc
            except FileNotFoundError as exc:
                raise RuntimeError(f"age binary not found: {exc}") from exc
        finally:
            # Always remove the intermediate plaintext tar — even on
            # failure — so we never leave plaintext on disk.
            try:
                tar_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover
                pass

        if not encrypted_path.is_file():
            raise RuntimeError(
                "age produced no output file; refusing to record success"
            )
        _chmod_secure(encrypted_path)
        _fsync_path(encrypted_path)
        encrypted_bytes = encrypted_path.stat().st_size

        # ── checksum (post-fsync, §8.3 silent-corruption gate) ────────
        digest = _sha256_file(encrypted_path)
        checksum_path = window_dir / CHECKSUM_NAME
        checksum_path.write_text(
            f"{digest}  {ENCRYPTED_NAME}\n", encoding="utf-8",
        )
        _chmod_secure(checksum_path)
        _fsync_path(checksum_path)

        # ── manifest ──────────────────────────────────────────────────
        manifest_path = window_dir / MANIFEST_NAME
        manifest_path.write_text(
            (
                "{"
                f'"fire_window_id":"{fire_window_id}",'
                f'"dump_bytes":{dump_bytes},'
                f'"encrypted_bytes":{encrypted_bytes},'
                f'"sha256":"{digest}",'
                f'"pg_jobs":{int(self.pg_jobs)},'
                f'"format":"{format_label}"'
                "}\n"
            ),
            encoding="utf-8",
        )
        _chmod_secure(manifest_path)
        _fsync_path(manifest_path)

        # Drop the intermediate Postgres dump artefact now that the
        # encrypted blob is durable on disk; it would otherwise double
        # the storage cost of every backup. Directory format → rmtree;
        # custom (-Fc) format → unlink.
        try:
            if use_directory:
                shutil.rmtree(dump_target)
            else:
                dump_target.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover
            _log.warning("cleanup %s failed: %s", dump_target, exc)

        _log.info(
            "pg_dump+age window=%s dump_bytes=%d encrypted_bytes=%d sha256=%s",
            fire_window_id, dump_bytes, encrypted_bytes, digest[:16],
        )
        return (int(dump_bytes), int(encrypted_bytes))

    def _write_quarantine_meta_csv(self, window_dir: Path) -> None:
        """Write the sanitized ``quarantine_samples`` projection.

        Invokes ``psql --csv -c "<projection SQL>"`` against the
        configured DSN, captures stdout, and writes it to
        ``<window_dir>/negelir.quarantine_meta.csv`` with mode 0o600
        + fsync. A failure to produce the CSV is fatal — silently
        skipping it would let the encrypted dump ship without the
        forensic-evidence companion file the §8.3 contract promises.
        """
        psql = self.psql_binary or shutil.which("psql") or "psql"
        argv = [
            psql,
            "--no-psqlrc",
            "--csv",
            "--tuples-only=off",
            "--dbname", self.pg_dsn,
            "-c", _QUARANTINE_META_SQL,
        ]
        _log.info(
            "psql quarantine-meta argv=%s",
            shlex.join(argv[:-3] + ["<dsn-redacted>", "-c", "<sql>"]),
        )
        try:
            result = self.runner(argv)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace")[:2048]
            raise RuntimeError(
                f"psql quarantine-meta failed (rc={exc.returncode}): "
                f"{stderr.strip()}"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"psql binary not found: {exc}") from exc

        meta_path = window_dir / QUARANTINE_META_NAME
        payload = result.stdout or b""
        meta_path.write_bytes(payload)
        _chmod_secure(meta_path)
        _fsync_path(meta_path)


def _dir_size(path: Path) -> int:
    """Sum file sizes under ``path`` (recursive)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:  # pragma: no cover
                continue
    return total


_NOTICE_TOTAL_RE = re.compile(r"pruned_total=(\d+)")


@dataclass(frozen=True)
class _PruneSpec:
    table_candidates: tuple[str, ...]
    where_sql: str
    order_col: str


def _sql_quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class LocalPgPruner:
    """Live Postgres-backed TTL pruner for Phase 8.3.

    Implements the ``PrunerStorage`` protocol consumed by
    ``MaintBackupAgent``:

    * Deletes are performed in batched loops using ``LIMIT`` and
      ordered ``ctid`` victim selection.
    * Each table prune runs in a single server-side transactional
      ``DO`` block.
    * Missing tables are treated as zero-row no-ops (the migration
      surface is still converging).
    * ``dry_run=True`` returns would-delete counts without mutating
      rows.
    """

    def __init__(
        self,
        *,
        pg_dsn: str,
        prune_batch: int,
        sec_quarantine_ttl_days: int,
        schema_snapshot_retention_days: int,
        dlq_retention_days: int,
        audit_retention_days: int,
        runner: CommandRunner = _default_runner,
        psql_binary: Optional[str] = None,
    ) -> None:
        self._pg_dsn = str(pg_dsn or "").strip()
        self._batch = int(prune_batch)
        self._runner = runner
        self._psql_binary = psql_binary or shutil.which("psql") or "psql"
        self._specs: dict[str, _PruneSpec] = {
            "opsctl_audit": _PruneSpec(
                table_candidates=("opsctl_audit",),
                where_sql=(
                    "ts_utc < now() - interval "
                    f"'{int(audit_retention_days)} days'"
                ),
                order_col="ts_utc",
            ),
            "schema_snapshots": _PruneSpec(
                table_candidates=("schema_snapshots",),
                where_sql=(
                    "captured_at < now() - interval "
                    f"'{int(schema_snapshot_retention_days)} days'"
                ),
                order_col="captured_at",
            ),
            "pattern_allowlist": _PruneSpec(
                table_candidates=("pattern_allowlist",),
                where_sql="expires_at IS NOT NULL AND expires_at < now()",
                order_col="expires_at",
            ),
            "dlq_entries": _PruneSpec(
                table_candidates=("dlq_entries",),
                where_sql=(
                    "created_at < now() - interval "
                    f"'{int(dlq_retention_days)} days'"
                ),
                order_col="created_at",
            ),
            "quarantine_samples": _PruneSpec(
                table_candidates=("quarantine_samples",),
                where_sql=(
                    "detected_at < now() - interval "
                    f"'{int(sec_quarantine_ttl_days)} days'"
                ),
                order_col="detected_at",
            ),
            "maint_audit_log": _PruneSpec(
                table_candidates=("maint_audit_log", "maint_audit_log_pii"),
                where_sql=(
                    "produced_at < now() - interval "
                    f"'{int(audit_retention_days)} days'"
                ),
                order_col="produced_at",
            ),
        }

    def prune(self, *, dry_run: bool) -> Mapping[str, int]:
        from xops.maint.prune_order import PRUNE_ORDER

        out: dict[str, int] = {}
        for logical in PRUNE_ORDER:
            spec = self._specs[logical]
            table = self._resolve_table(spec.table_candidates)
            if table is None:
                out[logical] = 0
                continue
            if dry_run:
                out[logical] = self._count_where(table=table, where_sql=spec.where_sql)
            else:
                out[logical] = self._delete_batched(
                    table=table,
                    where_sql=spec.where_sql,
                    order_col=spec.order_col,
                )
        return out

    def _run_psql(self, sql: str) -> "subprocess.CompletedProcess[bytes]":
        argv = [
            self._psql_binary,
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--dbname", self._pg_dsn,
            "--set", "ON_ERROR_STOP=1",
            "-c", sql,
        ]
        return self._runner(argv)

    def _resolve_table(self, candidates: tuple[str, ...]) -> Optional[str]:
        for name in candidates:
            literal = _sql_quote_literal(f"public.{name}")
            sql = f"SELECT to_regclass({literal}) IS NOT NULL;"
            try:
                res = self._run_psql(sql)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                raise TableResolutionError(
                    f"psql existence probe failed for candidates {candidates!r}: {exc}"
                ) from exc
            raw = (res.stdout or b"").decode("utf-8", errors="replace").strip().lower()
            if raw in {"t", "true", "1"}:
                return name
        return None

    def _count_where(self, *, table: str, where_sql: str) -> int:
        sql = f"SELECT COUNT(*) FROM {table} WHERE {where_sql};"
        try:
            res = self._run_psql(sql)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            if "does not exist" in stderr:
                return 0
            raise
        raw = (res.stdout or b"").decode("utf-8", errors="replace").strip()
        try:
            return int(raw or "0")
        except ValueError:
            raise TableResolutionError(
                f"psql returned non-integer output for COUNT on {table!r}: {raw!r}"
            ) from None

    def _delete_batched(self, *, table: str, where_sql: str, order_col: str) -> int:
        sql = (
            "DO $$\n"
            "DECLARE\n"
            "  v_deleted INTEGER := 0;\n"
            "  v_total INTEGER := 0;\n"
            "BEGIN\n"
            "  LOOP\n"
            f"    WITH victims AS (\n"
            f"      SELECT ctid FROM {table}\n"
            f"      WHERE {where_sql}\n"
            f"      ORDER BY {order_col} ASC\n"
            f"      LIMIT {int(self._batch)}\n"
            "    ), del AS (\n"
            f"      DELETE FROM {table} t\n"
            "      USING victims v\n"
            "      WHERE t.ctid = v.ctid\n"
            "      RETURNING 1\n"
            "    )\n"
            "    SELECT COUNT(*) INTO v_deleted FROM del;\n"
            "    v_total := v_total + v_deleted;\n"
            "    EXIT WHEN v_deleted = 0;\n"
            "  END LOOP;\n"
            "  RAISE NOTICE 'pruned_total=%', v_total;\n"
            "END $$;"
        )
        try:
            res = self._run_psql(sql)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            if "does not exist" in stderr:
                return 0
            raise
        text = (
            (res.stdout or b"").decode("utf-8", errors="replace")
            + "\n"
            + (res.stderr or b"").decode("utf-8", errors="replace")
        )
        m = _NOTICE_TOTAL_RE.search(text)
        if m is None:
            return 0
        return int(m.group(1))


# §8.3 binding: Restore-verify failure quarantines the bad dump dir.
# Suffix appended to the per-fire-window directory name; the next
# nightly cron therefore does not see the failed run as today's
# success and the disk-usage guard still accounts for the on-disk
# bytes.  The rename is best-effort: a missing source dir is treated
# as a no-op (the in-memory shim verifier path used by the test
# suite never writes a window dir).
FAILED_DIR_SUFFIX: str = ".failed"


def safe_window_name(fire_window_id: str) -> str:
    """Sanitize a ``fire_window_id`` (which may be an ISO timestamp
    containing ``:`` / ``/``) into a safe filename component.

    Mirrors the in-line transform in ``LocalPgDumpExecutor.dump`` so
    the agent's verify-failure quarantine path computes the SAME
    window directory the dump executor wrote to, without re-deriving
    the rule by hand.
    """

    return fire_window_id.replace(":", "_").replace("/", "_")


def quarantine_failed_dump_dir(
    *, backup_dir: str, fire_window_id: str,
) -> Optional[Path]:
    """Rename ``<backup_dir>/<safe_window>/`` →
    ``<backup_dir>/<safe_window>.failed/`` after a verify failure.

    Returns the new path on a successful rename, ``None`` if the
    source dir does not exist (which is the dominant case in the
    pure-Python test path that uses ``NoopVerifier`` /
    ``NoopDumpExecutor``). If a ``<safe_window>.failed/`` already
    exists from a prior failure on the same window (catch-up replay
    of the same window-id), the rename appends a numeric suffix to
    avoid clobbering forensic evidence.

    The function NEVER raises into the agent's state machine — any
    OSError is logged and swallowed; the verify-fail emit path must
    always complete so the operator-paging ``sec.alert.v1`` lands.
    """

    src = Path(backup_dir) / safe_window_name(fire_window_id)
    if not src.exists():
        return None
    dst = src.with_name(src.name + FAILED_DIR_SUFFIX)
    if dst.exists():
        # Disambiguate while preserving prior evidence.
        i = 2
        while True:
            candidate = src.with_name(f"{src.name}{FAILED_DIR_SUFFIX}.{i}")
            if not candidate.exists():
                dst = candidate
                break
            i += 1
    try:
        src.rename(dst)
    except OSError as exc:
        _log.warning(
            "xops.backup.quarantine_failed_dump_dir: rename %s -> %s "
            "failed: %r", src, dst, exc,
        )
        return None
    return dst


__all__ = [
    "CHECKSUM_NAME",
    "CommandRunner",
    "DUMP_DIR_NAME",
    "DUMP_FILE_NAME",
    "ENCRYPTED_NAME",
    "FAILED_DIR_SUFFIX",
    "LocalPgDumpExecutor",
    "LocalPgPruner",
    "MANIFEST_NAME",
    "QUARANTINE_META_NAME",
    "quarantine_failed_dump_dir",
    "safe_window_name",
]
