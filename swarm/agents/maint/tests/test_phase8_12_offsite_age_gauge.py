"""Phase 8 §8.12 — offsite age gauge + watchdog alert tests.

Bullet: **Offsite age gauge.** Telemetry exposes
``maint_backup_offsite_age_hours`` (now − last successful
``kind=backup_offsite_uploaded``); separate from
``maint_backup_age_hours``. Watchdog
``sec.alert.v1{kind=backup_age_alert, scope=offsite,
severity=critical}`` fires when offsite age >
``cfg.maint_backup_offsite_age_alert_h`` (default 48h).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    Message,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)
from swarm.agents.topics import MAINT_EVENT, SEC_ALERT

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


def _build_agent(
    clock: _StubClock,
    backup_dir: str = "/nonexistent/negelir_test_backup",
) -> MaintBackupAgent:
    _prior = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = backup_dir  # type: ignore[attr-defined]
    try:
        agent = MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=NoopVerifier(),
            pruner=InMemoryPrunerStorage(counts={}),
            quarantine=InMemoryQuarantineStore(rows_per_client={}),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3, last_dump_bytes=0),
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "fixed-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = _prior  # type: ignore[attr-defined]
    return agent


def _alerts(msgs: Iterable[Message], kind: str | None = None) -> list[Message]:
    return [
        m for m in msgs
        if m.envelope.topic == SEC_ALERT
        and (kind is None or m.payload.get("kind") == kind)
    ]


# ── offsite_age_hours() ───────────────────────────────────────────────────────

def test_offsite_age_hours_none_before_first_upload() -> None:
    """offsite_age_hours() returns None before any upload is recorded."""
    clock = _StubClock(_t(2025, 1, 1))
    agent = _build_agent(clock)
    assert agent.offsite_age_hours() is None


def test_offsite_age_hours_after_simulated_upload() -> None:
    """offsite_age_hours() reports hours since last upload correctly."""
    clock = _StubClock(_t(2025, 1, 1, 0))
    agent = _build_agent(clock)
    agent._last_offsite_uploaded_wall = _t(2025, 1, 1, 2, 0)
    clock.set(_t(2025, 1, 1, 10, 0))  # 8 hours later
    age = agent.offsite_age_hours()
    assert age is not None
    assert abs(age - 8.0) < 0.01


# ── metrics_snapshot() includes offsite gauge ────────────────────────────────

def test_metrics_snapshot_includes_offsite_key() -> None:
    """metrics_snapshot() must expose maint_backup_offsite_age_hours."""
    clock = _StubClock(_t(2025, 1, 1))
    agent = _build_agent(clock)
    snap = agent.metrics_snapshot()
    assert "maint_backup_offsite_age_hours" in snap


def test_metrics_snapshot_offsite_none_before_upload() -> None:
    """maint_backup_offsite_age_hours is None when no upload yet."""
    clock = _StubClock(_t(2025, 1, 1))
    agent = _build_agent(clock)
    snap = agent.metrics_snapshot()
    assert snap["maint_backup_offsite_age_hours"] is None


def test_metrics_snapshot_offsite_separate_from_onhost() -> None:
    """offsite gauge is independent of on-host verified backup gauge."""
    clock = _StubClock(_t(2025, 1, 1, 0))
    agent = _build_agent(clock)
    agent._last_verified_wall = _t(2025, 1, 1, 0)
    clock.set(_t(2025, 1, 1, 5))
    snap = agent.metrics_snapshot()
    assert snap['maint_backup_age_hours{verified="true"}'] is not None
    assert snap["maint_backup_offsite_age_hours"] is None


def test_metrics_snapshot_offsite_reports_value_after_upload() -> None:
    """maint_backup_offsite_age_hours is non-None after an upload is recorded."""
    clock = _StubClock(_t(2025, 1, 1, 0))
    agent = _build_agent(clock)
    agent._last_offsite_uploaded_wall = _t(2025, 1, 1, 0)
    clock.set(_t(2025, 1, 1, 12))
    snap = agent.metrics_snapshot()
    age = snap["maint_backup_offsite_age_hours"]
    assert age is not None
    assert abs(age - 12.0) < 0.01


# ── watchdog alert ────────────────────────────────────────────────────────────

def test_offsite_age_watchdog_fires_critical_backup_age_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When offsite age exceeds threshold, kind=backup_age_alert
    severity=critical with scope=offsite in the reason is emitted."""
    monkeypatch.setattr(_cfg, "maint_backup_offsite_age_alert_h", 2)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 2 * * *")
    clock = _StubClock(_t(2025, 1, 1, 0))
    agent = _build_agent(clock)
    # Upload was 3h ago (> 2h threshold).
    agent._last_offsite_uploaded_wall = _t(2024, 12, 31, 21, 0)
    msgs = list(agent.flush_expired())
    alerts = _alerts(msgs, kind="backup_age_alert")
    assert alerts, "expected backup_age_alert to fire for offsite age breach"
    payload = alerts[0].payload
    assert payload["severity"] == "critical"
    assert "scope=offsite" in payload["reason"]


def test_offsite_age_watchdog_uses_canonical_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Watchdog must emit kind=backup_age_alert, not backup_offsite_age_alert."""
    monkeypatch.setattr(_cfg, "maint_backup_offsite_age_alert_h", 1)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 2 * * *")
    clock = _StubClock(_t(2025, 6, 1, 0))
    agent = _build_agent(clock)
    agent._last_offsite_uploaded_wall = _t(2025, 5, 31, 22, 0)  # 2h ago
    msgs = list(agent.flush_expired())
    bad_kinds = _alerts(msgs, kind="backup_offsite_age_alert")
    assert not bad_kinds, (
        "backup_offsite_age_alert is not a known kind; use backup_age_alert"
    )


def test_offsite_age_watchdog_no_fire_when_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Watchdog does not fire when offsite upload is recent."""
    monkeypatch.setattr(_cfg, "maint_backup_offsite_age_alert_h", 48)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 2 * * *")
    clock = _StubClock(_t(2025, 1, 1, 3))
    agent = _build_agent(clock)
    agent._last_offsite_uploaded_wall = _t(2025, 1, 1, 2, 30)  # 30 min ago
    msgs = list(agent.flush_expired())
    offsite_alerts = [
        m for m in _alerts(msgs, kind="backup_age_alert")
        if "scope=offsite" in (m.payload.get("reason") or "")
    ]
    assert not offsite_alerts, "watchdog must not fire when offsite upload is recent"


def test_offsite_age_watchdog_no_fire_before_first_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Watchdog does not fire (boot-warm guard) when no upload yet recorded."""
    monkeypatch.setattr(_cfg, "maint_backup_offsite_age_alert_h", 1)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 2 * * *")
    clock = _StubClock(_t(2025, 1, 1, 12))
    agent = _build_agent(clock)
    # No _last_offsite_uploaded_wall set.
    msgs = list(agent.flush_expired())
    offsite_alerts = [
        m for m in _alerts(msgs, kind="backup_age_alert")
        if "scope=offsite" in (m.payload.get("reason") or "")
    ]
    assert not offsite_alerts, "boot-warm guard: must not fire before first upload"


def test_offsite_age_watchdog_debounced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Watchdog fires at most once per alert-threshold window."""
    monkeypatch.setattr(_cfg, "maint_backup_offsite_age_alert_h", 2)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 2 * * *")
    clock = _StubClock(_t(2025, 1, 1, 0))
    agent = _build_agent(clock)
    agent._last_offsite_uploaded_wall = _t(2024, 12, 31, 20, 0)  # 4h ago

    # First flush → should fire.
    msgs1 = list(agent.flush_expired())
    first_alerts = [
        m for m in _alerts(msgs1, kind="backup_age_alert")
        if "scope=offsite" in (m.payload.get("reason") or "")
    ]
    assert first_alerts, "expected first alert to fire"

    # Second flush 30 min later — within the debounce window, must NOT fire.
    clock.set(_t(2025, 1, 1, 0, 30))
    msgs2 = list(agent.flush_expired())
    second_alerts = [
        m for m in _alerts(msgs2, kind="backup_age_alert")
        if "scope=offsite" in (m.payload.get("reason") or "")
    ]
    assert not second_alerts, "watchdog must be debounced within the alert window"
