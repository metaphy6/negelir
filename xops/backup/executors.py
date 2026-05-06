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
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Protocol, Sequence


_log = logging.getLogger("xops.backup.executors")


# Filenames inside the per-fire-window directory. Pinned so the
# verifier + restore CLI can find them without an inventory probe.
DUMP_DIR_NAME: str = "dump.d"
ENCRYPTED_NAME: str = "dump.tar.age"
CHECKSUM_NAME: str = "negelir.checksum.txt"
MANIFEST_NAME: str = "manifest.json"


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
        dump_dir = window_dir / DUMP_DIR_NAME
        _ensure_secure_dir(dump_dir)

        # ── pg_dump ────────────────────────────────────────────────────
        pg_dump = self.pg_dump_binary or shutil.which("pg_dump") or "pg_dump"
        argv = [
            pg_dump,
            "--format=directory",
            f"--jobs={int(self.pg_jobs)}",
            "--no-owner",
            "--no-privileges",
            "--file", str(dump_dir),
            "--dbname", self.pg_dsn,
        ]
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

        dump_bytes = _dir_size(dump_dir)

        # ── tar + age encrypt ─────────────────────────────────────────
        encrypted_path = window_dir / ENCRYPTED_NAME
        tar_path = window_dir / "_dump.tar"
        try:
            with tarfile.open(tar_path, "w") as tar:
                tar.add(dump_dir, arcname=DUMP_DIR_NAME)
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
                f'"pg_jobs":{int(self.pg_jobs)}'
                "}\n"
            ),
            encoding="utf-8",
        )
        _chmod_secure(manifest_path)
        _fsync_path(manifest_path)

        # Drop the intermediate Postgres dump directory now that the
        # encrypted artefact is durable on disk; it would otherwise
        # double the storage cost of every backup.
        try:
            shutil.rmtree(dump_dir)
        except OSError as exc:  # pragma: no cover
            _log.warning("rmtree %s failed: %s", dump_dir, exc)

        _log.info(
            "pg_dump+age window=%s dump_bytes=%d encrypted_bytes=%d sha256=%s",
            fire_window_id, dump_bytes, encrypted_bytes, digest[:16],
        )
        return (int(dump_bytes), int(encrypted_bytes))


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


__all__ = [
    "CHECKSUM_NAME",
    "CommandRunner",
    "DUMP_DIR_NAME",
    "ENCRYPTED_NAME",
    "LocalPgDumpExecutor",
    "MANIFEST_NAME",
]
