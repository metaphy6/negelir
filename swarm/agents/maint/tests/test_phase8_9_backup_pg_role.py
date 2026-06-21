"""Phase 8 §8.9 DoD — Backup PG role enforcement proof tests.

Covers:

* **fail_safe_wrong_pg_role**: attempting to start the backup agent
  under a role other than ``cfg.maint_backup_pg_role`` (default
  ``negelir_backup``) raises :class:`BackupRoleError` carrying the
  ``fail_safe_wrong_pg_role`` surface code.

* **fail_safe_superuser**: attempting to start the backup agent
  under the expected role name but with ``is_superuser=True``
  raises :class:`BackupRoleError` carrying the ``fail_safe_superuser``
  surface code.
"""
from __future__ import annotations

import pytest

from swarm.agents.maint.backup import (
    BackupRoleError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgRoleChecker,
    NoopVerifier,
    StaticDiskGauge,
)


def _build(pg_role_checker: NoopPgRoleChecker) -> MaintBackupAgent:
    """Construct a :class:`MaintBackupAgent` with all other checks
    bypassed so only the PG-role gate is under test."""
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        pg_role_checker=pg_role_checker,
    )


def test_refuse_wrong_pg_role() -> None:
    """§8.9 DoD: starting the backup agent under a non-negelir_backup
    role raises BackupRoleError with fail_safe_wrong_pg_role."""
    checker = NoopPgRoleChecker(role_name="postgres", is_superuser=False)
    with pytest.raises(BackupRoleError) as exc_info:
        _build(checker)
    assert "fail_safe_wrong_pg_role" in str(exc_info.value)
    assert "postgres" in str(exc_info.value)


def test_refuse_superuser_pg_role() -> None:
    """§8.9 DoD: starting the backup agent as negelir_backup but with
    superuser privileges raises BackupRoleError with fail_safe_superuser."""
    checker = NoopPgRoleChecker(role_name="negelir_backup", is_superuser=True)
    with pytest.raises(BackupRoleError) as exc_info:
        _build(checker)
    assert "fail_safe_superuser" in str(exc_info.value)


def test_correct_role_and_not_superuser_starts_ok() -> None:
    """Sanity: the default NoopPgRoleChecker (negelir_backup, not superuser)
    allows the agent to start without raising BackupRoleError."""
    checker = NoopPgRoleChecker(role_name="negelir_backup", is_superuser=False)
    agent = _build(checker)
    assert agent is not None
