"""Phase 8 §8.9 DoD — Backup unencrypted-in-prod proof tests.

Covers:

* **fail_safe_no_encryption_in_prod** (prod): profile=prod,
  encryption_key_dir unset -> :class:`BackupConfigError` with
  surface code fail_safe_no_encryption_in_prod at agent startup.

* **Mock profile warn + emit**: profile=mock (or any non-prod
  profile), encryption not configured -> on the first
  flush_expired() tick, a sec.alert.v1{kind=backup_unencrypted,
  severity=warn} is published.

* **Debounced daily**: a second flush_expired() call within the
  same UTC day does NOT re-emit backup_unencrypted; a call on the
  next UTC day DOES.

* **Encrypted mock profile silent**: when maint_backup_encryption_key_dir
  is set (even on mock profile), no backup_unencrypted is emitted.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    BackupConfigError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgRoleChecker,
    NoopRecipientCounter,
    NoopVerifier,
    StaticDiskGauge,
)
from swarm.agents.topics import SEC_ALERT

UTC = timezone.utc


def _t(year: int, month: int, day: int, hour: int = 3, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def wall(self) -> datetime:
        return self.now

    def set(self, when: datetime) -> None:
        self.now = when


def _build_agent(
    monkeypatch,
    clock: _StubClock,
    *,
    profile: str = "mock",
    encryption_key_dir: str = "",
    recipients_file: str = "",
) -> MaintBackupAgent:
    monkeypatch.setattr(_cfg, "profile", profile, raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", encryption_key_dir, raising=False,
    )
    monkeypatch.setattr(
        _cfg, "maint_backup_age_recipients_file", recipients_file, raising=False,
    )
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
        clock_wall=clock.wall,
        clock_mono_ns=lambda: int(clock.wall().timestamp() * 1e9),
        new_id=lambda: "fixed-id",
        enforce_permissions=False,
        pg_role_checker=NoopPgRoleChecker(
            role_name="negelir_backup", is_superuser=False,
        ),
        recipient_counter=NoopRecipientCounter(recipient_count=2),
    )


def _sec_alert_kinds(msgs) -> list:
    return [
        (m.payload or {}).get("kind")
        for m in msgs
        if m.envelope.topic == SEC_ALERT
    ]


# -- fail_safe_no_encryption_in_prod -----------------------------------------------


def test_prod_profile_no_encryption_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prod profile + no encryption surface -> BackupConfigError
    with surface code fail_safe_no_encryption_in_prod."""
    monkeypatch.setattr(_cfg, "profile", "prod", raising=False)
    monkeypatch.setattr(_cfg, "maint_runtime", "compose", raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_encryption_key_dir", "", raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_age_recipients_file", "", raising=False)
    with pytest.raises(BackupConfigError, match="fail_safe_no_encryption_in_prod"):
        MaintBackupAgent(
            dump=NoopDumpExecutor(),
            verifier=NoopVerifier(),
            pruner=InMemoryPrunerStorage(),
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            enforce_permissions=False,
            pg_role_checker=NoopPgRoleChecker(),
            recipient_counter=NoopRecipientCounter(recipient_count=2),
        )


# -- Mock profile: warn + emit backup_unencrypted ----------------------------------


def test_mock_profile_unencrypted_emits_backup_unencrypted_on_first_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mock profile + no encryption -> flush_expired emits
    sec.alert.v1{kind=backup_unencrypted, severity=warn}."""
    clock = _StubClock(_t(2025, 6, 1))
    agent = _build_agent(monkeypatch, clock, profile="mock", encryption_key_dir="")
    msgs = list(agent.flush_expired())
    kinds = _sec_alert_kinds(msgs)
    assert "backup_unencrypted" in kinds
    for m in msgs:
        if (m.payload or {}).get("kind") == "backup_unencrypted":
            assert m.payload["severity"] == "warn"
            break


def test_mock_profile_unencrypted_debounced_same_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """second flush_expired within the same UTC day does NOT
    re-emit backup_unencrypted (debounced daily)."""
    clock = _StubClock(_t(2025, 6, 1, 3))
    agent = _build_agent(monkeypatch, clock, profile="mock", encryption_key_dir="")
    # First flush: emits
    msgs1 = list(agent.flush_expired())
    assert "backup_unencrypted" in _sec_alert_kinds(msgs1)
    # Second flush same UTC day (1 hour later)
    clock.set(_t(2025, 6, 1, 4))
    msgs2 = list(agent.flush_expired())
    assert "backup_unencrypted" not in _sec_alert_kinds(msgs2)


def test_mock_profile_unencrypted_reemits_next_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the UTC date rolls over, backup_unencrypted re-fires
    (daily debounce re-arms on new UTC day)."""
    clock = _StubClock(_t(2025, 6, 1, 3))
    agent = _build_agent(monkeypatch, clock, profile="mock", encryption_key_dir="")
    # Day 1: first emit
    list(agent.flush_expired())
    # Day 2: next UTC day -> re-emit
    clock.set(_t(2025, 6, 2, 3))
    msgs = list(agent.flush_expired())
    assert "backup_unencrypted" in _sec_alert_kinds(msgs)


def test_mock_profile_with_encryption_key_dir_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mock profile with encryption_key_dir set -> no backup_unencrypted."""
    clock = _StubClock(_t(2025, 6, 1))
    agent = _build_agent(
        monkeypatch, clock, profile="mock", encryption_key_dir="/keys/mock",
    )
    msgs = list(agent.flush_expired())
    assert "backup_unencrypted" not in _sec_alert_kinds(msgs)


def test_mock_profile_with_recipients_file_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mock profile with age_recipients_file set -> no backup_unencrypted."""
    clock = _StubClock(_t(2025, 6, 1))
    agent = _build_agent(
        monkeypatch, clock, profile="mock",
        recipients_file="/etc/backup/recipients.txt",
    )
    msgs = list(agent.flush_expired())
    assert "backup_unencrypted" not in _sec_alert_kinds(msgs)
