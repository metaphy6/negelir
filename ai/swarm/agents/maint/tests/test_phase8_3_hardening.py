"""Phase 8 §8.3 hardening — backup-age gauge + permission audit tests.

Covers the unticked ROADMAP §8.3 bullets that are landable as
agent-side first cuts (cold-verify cron + ops.restore CLI are
separate diffs):

* :meth:`MaintBackupAgent.backup_age_hours` — silent-failure mode
  visibility. Pre-first-run returns ``None``; only ``outcome=ok``
  runs satisfy ``verified=True``.
* :meth:`MaintBackupAgent.backup_age_alert_due` — watchdog gate
  honours ``cfg.maint_backup_age_alert_h``.
* :meth:`MaintBackupAgent.check_permissions` — refuses 0o755 dirs
  / 0o644 files; tolerates non-POSIX filesystems (mode==0).
"""
from __future__ import annotations

import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from common.config import cfg as _cfg
from ai.swarm.agents.maint.backup import MaintBackupAgent


@pytest.fixture
def freezer():
    """Tiny mutable wall-clock fixture."""

    class Freezer:
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        def __call__(self) -> datetime:
            return self.now

        def advance(self, hours: float) -> None:
            self.now = self.now + timedelta(hours=hours)

    return Freezer()


def test_backup_age_hours_none_before_first_run(freezer):
    agent = MaintBackupAgent(clock_wall=freezer)
    assert agent.backup_age_hours(verified=True) is None
    assert agent.backup_age_hours(verified=False) is None
    # Watchdog refuses to fire on cold start.
    assert agent.backup_age_alert_due() is False


def test_backup_age_hours_advances_with_clock(freezer):
    agent = MaintBackupAgent(clock_wall=freezer)
    # Simulate a verified ok completion at t=0.
    agent._last_verified_wall = freezer()  # type: ignore[attr-defined]
    agent._last_completed_wall = freezer()  # type: ignore[attr-defined]
    freezer.advance(5.0)
    age = agent.backup_age_hours(verified=True)
    assert age is not None and abs(age - 5.0) < 1e-6


def test_verified_gauge_only_advances_on_ok_outcome(freezer):
    """A failed verify run must NOT satisfy verified=True — that is
    the explicit binding contract (silent-failure mode is the threat)."""
    agent = MaintBackupAgent(clock_wall=freezer)
    # Simulate a "completed but verify failed" run by setting only
    # the any-outcome anchor (matches what backup.py would do for
    # outcome=verify_failed if the state machine reached the tail —
    # which it does not today, so this is forward-protective).
    agent._last_completed_wall = freezer()  # type: ignore[attr-defined]
    freezer.advance(2.0)
    assert agent.backup_age_hours(verified=False) == pytest.approx(2.0, abs=1e-6)
    # verified=True still None.
    assert agent.backup_age_hours(verified=True) is None


def test_backup_age_alert_due_above_threshold(freezer, monkeypatch):
    monkeypatch.setattr(_cfg, "maint_backup_age_alert_h", 24, raising=False)
    agent = MaintBackupAgent(clock_wall=freezer)
    agent._last_verified_wall = freezer()  # type: ignore[attr-defined]
    freezer.advance(23.0)
    assert agent.backup_age_alert_due() is False
    freezer.advance(2.0)  # now 25h
    assert agent.backup_age_alert_due() is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_check_permissions_clean_dir_passes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    os.chmod(tmp_path, 0o700)
    f = tmp_path / "negelir.dump"
    f.write_bytes(b"x")
    os.chmod(f, 0o600)
    agent = MaintBackupAgent()
    assert agent.check_permissions() == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_check_permissions_flags_loose_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    os.chmod(tmp_path, 0o755)  # group/other can read+exec → violation
    agent = MaintBackupAgent(enforce_permissions=False)
    violations = agent.check_permissions()
    assert any("0o755" in v or "looser" in v for v in violations), violations


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_check_permissions_flags_world_readable_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    os.chmod(tmp_path, 0o700)
    f = tmp_path / "negelir.dump"
    f.write_bytes(b"x")
    os.chmod(f, 0o644)  # world-readable → violation
    agent = MaintBackupAgent(enforce_permissions=False)
    violations = agent.check_permissions()
    assert any("looser" in v for v in violations), violations


def test_check_permissions_missing_dir_is_ok(tmp_path: Path, monkeypatch):
    """First run hasn't created the dir yet — not a violation."""
    missing = tmp_path / "does_not_exist_yet"
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(missing), raising=False)
    agent = MaintBackupAgent()
    assert agent.check_permissions() == []


# ── Startup enforcement (ROADMAP §8.3 "Permissions" checkbox) ──────────


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_init_refuses_loose_dir(tmp_path: Path, monkeypatch):
    """``enforce_permissions=True`` (the default) must raise on a
    backup dir that group/other can read or traverse."""
    from ai.swarm.agents.maint.backup import BackupPermissionError

    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    os.chmod(tmp_path, 0o755)
    with pytest.raises(BackupPermissionError) as exc_info:
        MaintBackupAgent()
    assert "0o755" in str(exc_info.value) or "looser" in str(exc_info.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_init_refuses_loose_file(tmp_path: Path, monkeypatch):
    """A 0o644 file inside an otherwise-clean 0o700 dir must also
    refuse-to-start — pg_dump output mode is the threat surface."""
    from ai.swarm.agents.maint.backup import BackupPermissionError

    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    os.chmod(tmp_path, 0o700)
    f = tmp_path / "stale.dump"
    f.write_bytes(b"x")
    os.chmod(f, 0o644)
    with pytest.raises(BackupPermissionError) as exc_info:
        MaintBackupAgent()
    assert "looser" in str(exc_info.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_init_sets_umask_0o077(tmp_path: Path, monkeypatch):
    """Successful boot leaves the process umask at ``0o077`` so any
    file the agent (or its subprocess) creates is 0o600 by default."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    os.chmod(tmp_path, 0o700)
    prev = os.umask(0o022)  # establish a known-loose umask first
    try:
        MaintBackupAgent()
        # Read the post-init umask without disturbing it permanently.
        current = os.umask(0o022)
        os.umask(current)
        assert current == 0o077
    finally:
        os.umask(prev)


def test_init_skips_enforcement_when_opted_out(tmp_path: Path, monkeypatch):
    """``enforce_permissions=False`` keeps the audit-only path open
    for tests that probe :meth:`check_permissions` directly."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path), raising=False)
    if os.name == "posix":
        os.chmod(tmp_path, 0o755)  # would normally refuse-to-start
    # Must NOT raise — opt-out honoured.
    agent = MaintBackupAgent(enforce_permissions=False)
    if os.name == "posix":
        assert agent.check_permissions(), "audit primitive still flags the dir"
