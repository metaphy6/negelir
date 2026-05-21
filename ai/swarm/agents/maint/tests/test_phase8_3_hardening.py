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


@pytest.fixture(autouse=True)
def _isolate_backup_dir(tmp_path_factory, monkeypatch):
    """Phase \u00a78.3 Scheduler bullet writes ``audit.csv`` under
    ``cfg.maint_backup_dir`` and replays it at boot \u2014 isolate every
    test so a prior run does not seed ``_last_completed_wall`` /
    ``_last_verified_wall`` and break the cold-start contracts
    below.

    Also set a dummy encryption_key_dir so the §8.9
    backup_unencrypted debounced-daily warn does not pollute tests
    that assert on specific sec.alert.v1 kinds.
    """
    isolated = tmp_path_factory.mktemp("backup_dir_iso")
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(isolated), raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "/test/keys", raising=False,
    )


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


# ── Backup-age telemetry surface + watchdog (ROADMAP §8.3 binding) ──────


def test_metrics_snapshot_exposes_labelled_age_gauge(freezer):
    """``metrics_snapshot()`` returns the
    ``maint_backup_age_hours{verified=...}`` gauge for both label
    values (operator-scrapable telemetry surface)."""
    agent = MaintBackupAgent(clock_wall=freezer)
    snap = agent.metrics_snapshot()
    assert set(snap.keys()) == {
        'maint_backup_age_hours{verified="true"}',
        'maint_backup_age_hours{verified="false"}',
        'maint_backup_offsite_age_hours',
    }
    # No qualifying dump yet → both labels report None (scrapers drop
    # the line; never substitute zero — that would falsely declare
    # freshness).
    assert snap['maint_backup_age_hours{verified="true"}'] is None
    assert snap['maint_backup_age_hours{verified="false"}'] is None
    # Simulate a verified completion at t=0; advance 4h.
    agent._last_verified_wall = freezer()  # type: ignore[attr-defined]
    agent._last_completed_wall = freezer()  # type: ignore[attr-defined]
    freezer.advance(4.0)
    snap = agent.metrics_snapshot()
    assert snap['maint_backup_age_hours{verified="true"}'] == pytest.approx(
        4.0, abs=1e-6,
    )
    assert snap['maint_backup_age_hours{verified="false"}'] == pytest.approx(
        4.0, abs=1e-6,
    )


def test_watchdog_emits_sec_alert_on_silent_failure(freezer, monkeypatch):
    """Heartbeat-driven watchdog fires
    ``sec.alert.v1{kind=backup_age_alert, severity=error,
    source=maint.backup.v1}`` when the verified-age gauge exceeds
    ``cfg.maint_backup_age_alert_h`` — the silent-failure mode where
    the agent is alive but every dump is failing verify."""
    monkeypatch.setattr(_cfg, "maint_backup_age_alert_h", 24, raising=False)
    # Use a far-future cron so the nightly state machine never fires
    # in this test — we are isolating the watchdog branch only.
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 3 31 12 *", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_cold_verify_cron", "0 5 31 12 0", raising=False,
    )
    agent = MaintBackupAgent(clock_wall=freezer)
    # Seed a verified completion at t=0.
    agent._last_verified_wall = freezer()  # type: ignore[attr-defined]
    # Below threshold — no alert.
    freezer.advance(20.0)
    msgs = list(agent.flush_expired())
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    assert alerts == []
    # Cross threshold — one alert.
    freezer.advance(10.0)  # now 30h, > 24h threshold
    msgs = list(agent.flush_expired())
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    assert len(alerts) == 1
    payload = alerts[0].payload
    assert payload["kind"] == "backup_age_alert"
    assert payload["severity"] == "error"
    assert payload["source"] == "maint.backup.v1"
    assert "30." in payload["reason"] or "30 " in payload["reason"]


def test_watchdog_debounced_within_window(freezer, monkeypatch):
    """Re-emission is debounced by one full
    ``cfg.maint_backup_age_alert_h`` window so a stuck-but-alive
    agent emits at most one alert per window — not one per
    heartbeat."""
    monkeypatch.setattr(_cfg, "maint_backup_age_alert_h", 24, raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 3 31 12 *", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_cold_verify_cron", "0 5 31 12 0", raising=False,
    )
    agent = MaintBackupAgent(clock_wall=freezer)
    agent._last_verified_wall = freezer()  # type: ignore[attr-defined]
    freezer.advance(30.0)  # > threshold
    first = list(agent.flush_expired())
    assert len([m for m in first if m.envelope.topic == "sec.alert.v1"]) == 1
    # Heartbeat 1 minute later — still over threshold but inside
    # debounce window → no second alert.
    freezer.advance(1.0 / 60.0)
    second = list(agent.flush_expired())
    assert [m for m in second if m.envelope.topic == "sec.alert.v1"] == []
    # Advance past one full window from the last fire — re-arm.
    freezer.advance(24.0)
    third = list(agent.flush_expired())
    assert len([m for m in third if m.envelope.topic == "sec.alert.v1"]) == 1


def test_watchdog_silent_before_first_run(freezer, monkeypatch):
    """Cold-start: no successful dump ever → watchdog refuses to
    fire (Phase 8.10 dead-mans-switch handles cold-start
    independently). Honours the ``backup_age_alert_due() is False``
    contract from the existing hardening tests."""
    monkeypatch.setattr(_cfg, "maint_backup_age_alert_h", 24, raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 3 31 12 *", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_cold_verify_cron", "0 5 31 12 0", raising=False,
    )
    agent = MaintBackupAgent(clock_wall=freezer)
    freezer.advance(72.0)  # 3 days, no seeded completion
    msgs = list(agent.flush_expired())
    assert [m for m in msgs if m.envelope.topic == "sec.alert.v1"] == []
