"""Phase 8 §8.3 — Postgres backup-role boot probe.

Refuse-to-start guard for the live :class:`LocalPgDumpExecutor`:
the dump pathway must run as the dedicated ``negelir_backup``
role (migration ``011_backup_role.sql``), never as the
application owner and never as a superuser.

The probe is a single ``psql`` call that returns
``current_user, is_superuser`` and parses the result. Any
mismatch raises :class:`BackupRoleError` — the swarm bootstrap
treats this as fatal so production never silently runs a dump
under the wrong identity.

Pure-stdlib, DI-friendly: tests inject a fake runner.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Mapping, Optional, Sequence

from xops.backup.executors import CommandRunner, _default_runner


_log = logging.getLogger("xops.backup.role_probe")

#: The PG role that MUST own the dump pathway (migration 011).
EXPECTED_BACKUP_ROLE: str = "negelir_backup"


class BackupRoleError(RuntimeError):
    """Refuse-to-start: PG identity does not match `negelir_backup`."""


def verify_backup_role(
    *,
    pg_dsn: str,
    runner: CommandRunner = _default_runner,
    psql_binary: Optional[str] = None,
    expected_role: str = EXPECTED_BACKUP_ROLE,
    pg_jobs: Optional[int] = None,
    headroom: int = 2,
) -> None:
    """Connect as the configured DSN and assert role identity.

    Raises :class:`BackupRoleError` if:

    * the DSN is empty (refuses to probe under an unset identity);
    * ``psql`` cannot be invoked;
    * the connected role is not ``expected_role``;
    * the connected role is a superuser (bypassing pg_read_all_data);
    * ``pg_jobs`` is set AND ``pg_jobs + headroom`` exceeds the
      role's ``rolconnlimit`` (a separate SQL probe). The default
      headroom of 2 mirrors §8.3 prose: leaves room for the
      verifier connection + a manual ad-hoc operator session.
    """
    if not pg_dsn:
        raise BackupRoleError(
            "verify_backup_role: pg_dsn is empty; cannot probe identity."
        )
    psql = psql_binary or shutil.which("psql") or "psql"
    argv: Sequence[str] = [
        psql,
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        "--field-separator=,",
        "--dbname", pg_dsn,
        "-c", "SELECT current_user, current_setting('is_superuser')",
    ]
    try:
        cp = runner(argv)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace")[:2048]
        raise BackupRoleError(
            f"verify_backup_role: psql failed (rc={exc.returncode}): "
            f"{stderr.strip()}"
        ) from exc
    except FileNotFoundError as exc:
        raise BackupRoleError(
            f"verify_backup_role: psql binary not found: {exc}"
        ) from exc

    raw = (cp.stdout or b"").decode(errors="replace").strip()
    if not raw:
        raise BackupRoleError(
            "verify_backup_role: psql produced empty output"
        )
    line = raw.splitlines()[0].strip()
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 2:
        raise BackupRoleError(
            f"verify_backup_role: unexpected psql output: {line!r}"
        )
    role, is_super = parts
    if role != expected_role:
        raise BackupRoleError(
            f"verify_backup_role: connected as {role!r}, "
            f"expected {expected_role!r}"
        )
    if is_super.lower() in ("on", "t", "true", "yes", "1"):
        raise BackupRoleError(
            f"verify_backup_role: role {role!r} is a superuser; "
            f"refuse-to-start"
        )

    # ── pg_jobs vs rolconnlimit probe ──────────────────────────────
    if pg_jobs is not None:
        _probe_connlimit(
            pg_dsn=pg_dsn, runner=runner, psql=psql,
            role=role, pg_jobs=int(pg_jobs), headroom=int(headroom),
        )

    _log.info(
        "verify_backup_role ok role=%s is_superuser=%s pg_jobs=%s",
        role, is_super, pg_jobs,
    )


def _probe_connlimit(
    *,
    pg_dsn: str,
    runner: CommandRunner,
    psql: str,
    role: str,
    pg_jobs: int,
    headroom: int,
) -> None:
    """Read ``pg_roles.rolconnlimit`` and refuse if too tight.

    A ``rolconnlimit`` of ``-1`` (unlimited) always passes.
    """
    argv: Sequence[str] = [
        psql,
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        "--dbname", pg_dsn,
        "-c", f"SELECT rolconnlimit FROM pg_roles WHERE rolname = '{role}'",
    ]
    try:
        cp = runner(argv)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace")[:2048]
        raise BackupRoleError(
            f"verify_backup_role: connlimit probe failed (rc={exc.returncode}): "
            f"{stderr.strip()}"
        ) from exc

    raw = (cp.stdout or b"").decode(errors="replace").strip()
    if not raw:
        raise BackupRoleError(
            f"verify_backup_role: rolconnlimit probe returned no rows "
            f"for role {role!r}"
        )
    try:
        connlimit = int(raw.splitlines()[0].strip())
    except ValueError as exc:
        raise BackupRoleError(
            f"verify_backup_role: rolconnlimit not an int: {raw!r}"
        ) from exc
    if connlimit == -1:
        return  # unlimited
    required = pg_jobs + headroom
    if connlimit < required:
        raise BackupRoleError(
            f"verify_backup_role: pg_jobs={pg_jobs} + headroom={headroom} "
            f"= {required} exceeds rolconnlimit={connlimit} on role "
            f"{role!r}; raise the role's CONNECTION LIMIT or lower "
            f"maint_backup_pg_jobs"
        )


__all__ = [
    "BackupRoleError",
    "EXPECTED_BACKUP_ROLE",
    "verify_backup_role",
]
