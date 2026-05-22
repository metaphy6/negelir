"""Phase 8 §8.13.6 DoD — PG password age hard cap proof tests.

Covers:

* **fail_safe_pg_secret_expired (a)**: starting the backup agent when
  ``pg_secret_age_days=121`` (> default max 120) raises
  :class:`BackupPermissionError` carrying ``fail_safe_pg_secret_expired``.

* **fail_safe_pg_secret_expired (b)**: the error message carries the
  observed age and the configured cap so the operator knows exactly
  what to fix.

* **safe-to-start (c)**: an age at the limit (120 days) passes
  unconditionally so the agent starts normally.
"""
from __future__ import annotations

import pytest

from ai.swarm.agents.maint.backup import (
    BackupPermissionError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgSecretAgeChecker,
    NoopVerifier,
    StaticDiskGauge,
)


def _build(pg_secret_age_checker: NoopPgSecretAgeChecker) -> MaintBackupAgent:
    """Construct a :class:`MaintBackupAgent` with all other checks
    bypassed so only the PG-secret-age gate is under test."""
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        pg_secret_age_checker=pg_secret_age_checker,
    )


def test_refuse_expired_pg_secret() -> None:
    """§8.13.6 (a): age=121 > max=120 raises BackupPermissionError with
    fail_safe_pg_secret_expired."""
    checker = NoopPgSecretAgeChecker(age_days=121)
    with pytest.raises(BackupPermissionError) as exc_info:
        _build(checker)
    assert "fail_safe_pg_secret_expired" in str(exc_info.value)


def test_error_message_carries_age_and_cap() -> None:
    """§8.13.6 (b): the error message includes the observed age and
    the configured cap so the operator sees what to fix."""
    checker = NoopPgSecretAgeChecker(age_days=200)
    with pytest.raises(BackupPermissionError) as exc_info:
        _build(checker)
    msg = str(exc_info.value)
    assert "200" in msg, f"age not in message: {msg!r}"
    assert "120" in msg, f"cap not in message: {msg!r}"


def test_at_limit_starts_ok() -> None:
    """§8.13.6 (c): age exactly at the max (120 days) passes so
    the agent starts normally."""
    checker = NoopPgSecretAgeChecker(age_days=120)
    agent = _build(checker)
    assert agent is not None
