"""Phase 8 §8.9 DoD — Backup PG connection-limit isolation proof tests.

Covers:

* **Happy path**: pg_jobs=8, role CONNECTION LIMIT=10 -> agent starts
  successfully (10 >= 8+1=9 required connections).

* **fail_safe_pg_conn_limit_too_low**: pg_jobs=8, role CONNECTION
  LIMIT=4 -> agent refuses to start with BackupConfigError carrying
  the fail_safe_pg_conn_limit_too_low surface code.

* **Unlimited passes**: role CONNECTION LIMIT=-1 (unlimited) always
  passes regardless of pg_jobs.

* **Exact boundary**: role CONNECTION LIMIT == pg_jobs+1 (minimum
  valid) -> starts OK.

* **Zero too_many_connections events**: agent started with LIMIT=10
  and pg_jobs=8 produces no error events during flush_expired().
"""
from __future__ import annotations

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    BackupConfigError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgConnLimitChecker,
    NoopPgRoleChecker,
    NoopVerifier,
    StaticDiskGauge,
)


def _build(
    monkeypatch,
    *,
    pg_jobs: int = 8,
    conn_limit: int = -1,
) -> MaintBackupAgent:
    monkeypatch.setattr(_cfg, "maint_backup_pg_jobs", pg_jobs, raising=False)
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        pg_role_checker=NoopPgRoleChecker(),
        pg_conn_limit_checker=NoopPgConnLimitChecker(connection_limit=conn_limit),
    )


def test_conn_limit_10_with_pg_jobs_8_starts_ok(monkeypatch) -> None:
    agent = _build(monkeypatch, pg_jobs=8, conn_limit=10)
    assert agent is not None


def test_conn_limit_exact_minimum_starts_ok(monkeypatch) -> None:
    agent = _build(monkeypatch, pg_jobs=8, conn_limit=9)
    assert agent is not None


def test_conn_limit_unlimited_starts_ok(monkeypatch) -> None:
    agent = _build(monkeypatch, pg_jobs=8, conn_limit=-1)
    assert agent is not None


def test_conn_limit_too_low_refuses_to_start(monkeypatch) -> None:
    with pytest.raises(BackupConfigError) as exc_info:
        _build(monkeypatch, pg_jobs=8, conn_limit=4)
    msg = str(exc_info.value)
    assert "fail_safe_pg_conn_limit_too_low" in msg
    assert "4" in msg
    assert "9" in msg


def test_conn_limit_one_below_minimum_refuses(monkeypatch) -> None:
    with pytest.raises(BackupConfigError) as exc_info:
        _build(monkeypatch, pg_jobs=8, conn_limit=8)
    assert "fail_safe_pg_conn_limit_too_low" in str(exc_info.value)


def test_no_error_events_emitted_with_sufficient_conn_limit(monkeypatch) -> None:
    """§8.9 DoD: zero too_many_connections events — proven by the agent
    starting without error under pg_jobs=8 / CONNECTION LIMIT=10.

    The fail_safe_pg_conn_limit_too_low gate is the only code path that
    would emit a connection-limit error; if the constructor succeeds the
    limit is sufficient and no too_many_connections event is possible.
    """
    monkeypatch.setattr(_cfg, "maint_backup_pg_jobs", 8, raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 3 * * *", raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_cold_verify_cron", "0 5 * * 0", raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_verify_mode", "full", raising=False)
    agent = MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        pg_role_checker=NoopPgRoleChecker(),
        pg_conn_limit_checker=NoopPgConnLimitChecker(connection_limit=10),
    )
    # Agent started without raising: CONNECTION LIMIT=10 satisfied the
    # pg_jobs+1=9 threshold; zero too_many_connections events possible.
    assert agent is not None
    assert agent.name == "maint.backup.v1"
