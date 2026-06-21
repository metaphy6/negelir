"""Phase 8 §8.9 DoD — second-pass proof: Failed dump quarantined.

Three assertions from the §8.9 second-pass prose:

* Dump dir is renamed to ``<safe_window>.failed/`` when
  ``pg_restore`` (RestoreVerifier) fails.
* The next cron tick (next UTC day) is NOT skipped — verify failure
  does NOT advance ``_last_completed_wall``, so the idempotency guard
  does not block the next-day run.
* The age gauge keeps reporting from the **last verified** dump, not
  from the failed run.

Existing coverage: ``test_phase8_3_backup.py::test_verify_failure_quarantines_existing_dump_dir``
already proves the rename in isolation. This module proves the
full three-assertion scenario end-to-end, exercising the real
``quarantine_failed_dump_dir`` helper against a ``tmp_path`` on
disk (not the no-op in-memory shim).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pytest

from common.config import cfg as _cfg
from ai.swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)
from xops.backup.executors import FAILED_DIR_SUFFIX, safe_window_name

UTC = timezone.utc


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def wall(self) -> datetime:
        return self.now

    def mono_ns(self) -> int:
        return int(self.now.timestamp() * 1_000_000_000)

    def set(self, when: datetime) -> None:
        self.now = when


@pytest.fixture(autouse=True)
def _force_live_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force dry_run=False so the fire state machine reaches the
    verify step (dry_run=True short-circuits before verify)."""
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", False)


def _build_agent(
    *,
    clock: _StubClock,
    verifier: NoopVerifier,
    backup_dir: str,
) -> MaintBackupAgent:
    prior = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = backup_dir  # type: ignore[attr-defined]
    try:
        return MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=verifier,
            pruner=InMemoryPrunerStorage(),
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "fixed-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = prior  # type: ignore[attr-defined]


def _fire_window_id(agent: MaintBackupAgent, fire_wall: datetime) -> str:
    """Reconstruct the fire_window_id the agent will use for ``fire_wall``."""
    return f"{agent._pod_instance_id}:{fire_wall.isoformat()}"  # noqa: SLF001


def _pre_create_dump_dir(backup_dir: Path, fwid: str) -> Path:
    """Create the per-window dir that a real DumpExecutor would produce."""
    window_dir = backup_dir / safe_window_name(fwid)
    window_dir.mkdir(parents=True, exist_ok=True)
    (window_dir / "dump.sql.age").write_text("fake encrypted dump bytes")
    return window_dir


# ── Test 1: failed dump dir renamed to <safe_window>.failed/ ────────────


def test_failed_dump_dir_renamed_to_failed_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failure → dump dir renamed to ``<safe_window>.failed/``
    and the ``backup_completed`` event carries the quarantined dir name."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))

    clock = _StubClock(_t(2025, 6, 10, 2, 30))
    agent = _build_agent(
        clock=clock,
        verifier=NoopVerifier(fail=True),
        backup_dir=str(tmp_path),
    )
    list(agent.flush_expired())  # arm

    # Advance to cron time (default 03:00 UTC).
    clock.set(_t(2025, 6, 10, 3, 0))
    fire_wall = _t(2025, 6, 10, 3, 0)
    fwid = _fire_window_id(agent, fire_wall)
    window_dir = _pre_create_dump_dir(tmp_path, fwid)
    safe = safe_window_name(fwid)

    msgs = list(agent.flush_expired())
    completed = next(
        m.payload for m in msgs if (m.payload or {}).get("kind") == "backup_completed"
    )

    # Assert outcome + quarantined dir name.
    assert completed["outcome"] == "verify_failed"
    assert completed["quarantined_dir"] == safe + FAILED_DIR_SUFFIX

    # Assert rename on disk.
    assert not window_dir.exists(), "original dump dir must be gone"
    failed_dir = tmp_path / (safe + FAILED_DIR_SUFFIX)
    assert failed_dir.is_dir(), "failed/ dir must exist"
    assert (failed_dir / "dump.sql.age").exists(), "evidence file preserved"


# ── Test 2: next cron does not skip the day ─────────────────────────────


def test_next_cron_fires_after_verify_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failure on day D must not prevent the backup from
    firing on day D+1 (``_last_completed_wall`` must NOT be set
    on a verify-failed run)."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))

    clock = _StubClock(_t(2025, 6, 10, 2, 30))
    agent = _build_agent(
        clock=clock,
        verifier=NoopVerifier(fail=True),
        backup_dir=str(tmp_path),
    )
    list(agent.flush_expired())  # arm

    # Day D: fire, verify fails.
    clock.set(_t(2025, 6, 10, 3, 0))
    list(agent.flush_expired())

    # Verify: _last_completed_wall is NOT set after a failure.
    assert agent._last_completed_wall is None, (  # noqa: SLF001
        "_last_completed_wall must not advance on verify failure"
    )

    # Day D+1: advance clock past the next-day cron slot.
    clock.set(_t(2025, 6, 11, 3, 0))
    msgs_day2 = list(agent.flush_expired())
    kinds_day2 = [(m.payload or {}).get("kind") for m in msgs_day2]

    # The backup must have fired on D+1 — backup_started must appear.
    assert "backup_started" in kinds_day2, (
        f"next-day cron must fire after verify failure; got kinds={kinds_day2}"
    )


# ── Test 3: age gauge keeps reporting from last verified dump ────────────


def test_age_gauge_stays_at_last_verified_after_verify_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a verify failure the ``backup_age_hours(verified=True)``
    gauge must keep reporting age from the **last successfully
    verified** dump, not from the failed run.

    Scenario:
      * Day D-1 03:00 — successful backup (sets _last_verified_wall).
      * Day D   03:00 — verify failure.
      * Gauge query at day D+1 00:00 — should be ~45 h from day D-1,
        NOT ~21 h from day D.
    """
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))

    # Day D-1: build agent with a prior verified run already seeded.
    # We set _last_verified_wall directly (simulating a boot-seed
    # from a previous successful audit row), which is the exact same
    # mechanism the agent uses in __init__ after reading audit.csv.
    clock = _StubClock(_t(2025, 6, 9, 2, 30))
    # First build succeeds.
    verifier_pass = NoopVerifier(fail=False)
    agent = _build_agent(
        clock=clock,
        verifier=verifier_pass,
        backup_dir=str(tmp_path),
    )
    list(agent.flush_expired())  # arm

    clock.set(_t(2025, 6, 9, 3, 0))
    list(agent.flush_expired())  # successful backup on day D-1

    last_verified = agent._last_verified_wall  # noqa: SLF001
    assert last_verified is not None, "setup: day D-1 successful backup required"

    # Switch verifier to failing for subsequent runs.
    agent._verifier = NoopVerifier(fail=True)  # noqa: SLF001

    # Day D: fire, verify fails.
    clock.set(_t(2025, 6, 10, 3, 0))
    list(agent.flush_expired())

    # _last_verified_wall must still be the day D-1 timestamp.
    assert agent._last_verified_wall == last_verified, (  # noqa: SLF001
        "_last_verified_wall must not advance on verify failure"
    )

    # Age gauge at day D+1 00:00.
    clock.set(_t(2025, 6, 11, 0, 0))
    age_h = agent.backup_age_hours(verified=True)
    assert age_h is not None

    expected_h = (
        (_t(2025, 6, 11, 0, 0) - last_verified).total_seconds() / 3600.0
    )
    # Allow a small floating-point tolerance.
    assert abs(age_h - expected_h) < 0.01, (
        f"age gauge should be ~{expected_h:.1f}h from last verified dump "
        f"(day D-1), got {age_h:.3f}h"
    )
