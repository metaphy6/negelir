"""Phase 8.9 — Backup wall-clock backwards/forward step proof tests.

What this asserts (binding §8.9 second-pass):

* Backwards wall-clock step of 600s (> default 300s threshold) skips
  the fire window and emits ``sec.alert.v1{kind=backup_clock_skew,
  severity=error}``.  No ``backup_started`` is published — the same
  ``backup_date_utc`` is never duplicated (idempotency preserved).
* Forward leap > 24h emits ``sec.alert.v1{kind=backup_clock_skew,
  severity=warn}`` with ``scope=forward`` present in the reason string.
* Catch-up policy: after a forward leap that exceeds
  ``cfg.maint_backup_max_skew_h``, exactly **one** make-up run fires on
  the first tick.  The second tick does NOT fire a second make-up run
  (``_catch_up_used`` guard prevents it).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)
from swarm.sdk.types import Message

UTC = timezone.utc


# ── helpers ─────────────────────────────────────────────────────────────


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


def _build_agent(*, clock: _StubClock) -> MaintBackupAgent:
    backup_dir = "/nonexistent/negelir_test_clockskew"
    _prior = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = backup_dir  # type: ignore[attr-defined]
    try:
        agent = MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=NoopVerifier(),
            pruner=InMemoryPrunerStorage(counts={"opsctl_audit": 1}),
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


def _payload_kinds(msgs: list[Message]) -> list[str]:
    return [(m.payload or {}).get("kind", "") for m in msgs]


# ── autouse fixture: dry_run=False + dummy encryption key ───────────────


@pytest.fixture(autouse=True)
def _force_live_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "/test/keys", raising=False,
    )


# ── 1. Backwards step of 600s: fire refused, error alert emitted ─────────


def test_backward_step_600s_skips_fire_and_emits_clock_skew_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step the clock back 600s mid-cron-window; assert the next tick
    refuses to fire (outcome=skew_skipped) AND emits
    ``sec.alert.v1{kind=backup_clock_skew, severity=error}``.
    Default ``maint_backup_clock_step_back_alert_s=300`` means 600s
    clearly exceeds the threshold.
    """
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_back_alert_s", 300)
    clock = _StubClock(_t(2025, 3, 1, 2, 30))
    agent = _build_agent(clock=clock)

    # arm + first fire at 03:00 → establishes _last_fire_wall
    list(agent.flush_expired())
    clock.set(_t(2025, 3, 1, 3, 0))
    list(agent.flush_expired())
    assert agent._last_fire_wall is not None  # noqa: SLF001 — test

    # Step back 600s (10 min) — beyond the 300s threshold.
    clock.set(_t(2025, 3, 1, 2, 50))
    # Force a fire by setting _next_fire_at to the stepped-back "now".
    agent._next_fire_at = _t(2025, 3, 1, 2, 49)  # noqa: SLF001 — test
    msgs = list(agent.flush_expired())

    # sec.alert.v1{backup_clock_skew, severity=error} MUST be emitted.
    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    assert any(
        a.payload["kind"] == "backup_clock_skew"
        and a.payload["severity"] == "error"
        and a.payload["source"] == "maint.backup.v1"
        for a in alerts
    ), f"expected backup_clock_skew/error among alerts, got {[a.payload for a in alerts]}"

    # backup_completed{skew_skipped} MUST be present.
    completed = next(
        (m.payload for m in msgs if m.payload.get("kind") == "backup_completed"),
        None,
    )
    assert completed is not None, "expected backup_completed"
    assert completed["outcome"] == "skew_skipped"


# ── 2. No duplicate backup_started for the same backup_date_utc ──────────


def test_backward_step_no_backup_started_emitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backwards clock step (600s) must NOT publish ``backup_started``
    — the same ``backup_date_utc`` is therefore never duplicated, keeping
    the at-most-one-run-per-UTC-day idempotency contract intact.
    """
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_back_alert_s", 300)
    clock = _StubClock(_t(2025, 3, 2, 2, 30))
    agent = _build_agent(clock=clock)

    list(agent.flush_expired())
    clock.set(_t(2025, 3, 2, 3, 0))
    list(agent.flush_expired())

    # Step clock back 600s and force a fire attempt.
    clock.set(_t(2025, 3, 2, 2, 50))
    agent._next_fire_at = _t(2025, 3, 2, 2, 49)  # noqa: SLF001 — test
    msgs = list(agent.flush_expired())

    assert not any(
        (m.payload or {}).get("kind") == "backup_started" for m in msgs
    ), "backup_started must not be published on a backwards-step fire"


# ── 3. Forward leap > 24h → severity=warn with scope=forward ─────────────


def test_forward_leap_24h_emits_warn_scope_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward leap above ``cfg.maint_backup_clock_step_forward_alert_h``
    (24h) emits ``sec.alert.v1{kind=backup_clock_skew, severity=warn}``
    with ``scope=forward`` present in the ``reason`` field.
    """
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_forward_alert_h", 24)
    monkeypatch.setattr(_cfg, "maint_backup_max_skew_h", 48)  # prevent catch-up
    clock = _StubClock(_t(2025, 3, 3, 2, 30))
    agent = _build_agent(clock=clock)

    list(agent.flush_expired())
    clock.set(_t(2025, 3, 3, 3, 0))
    list(agent.flush_expired())

    # Jump forward ~30h (> 24h threshold, < 48h catch-up threshold).
    clock.set(_t(2025, 3, 4, 9, 0))
    agent._next_fire_at = _t(2025, 3, 4, 8, 59)  # noqa: SLF001 — test
    msgs = list(agent.flush_expired())

    alerts = [m for m in msgs if m.envelope.topic == "sec.alert.v1"]
    warn_alert = next(
        (
            a for a in alerts
            if a.payload["kind"] == "backup_clock_skew"
            and a.payload["severity"] == "warn"
        ),
        None,
    )
    assert warn_alert is not None, (
        f"expected backup_clock_skew/warn among alerts, got {[a.payload for a in alerts]}"
    )
    reason: str = warn_alert.payload["reason"]
    assert "scope=forward" in reason, (
        f"expected 'scope=forward' in reason, got {reason!r}"
    )


# ── 4. Catch-up policy: exactly one make-up run ───────────────────────────


def test_catch_up_policy_fires_exactly_one_makeup_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a forward leap that exceeds ``cfg.maint_backup_max_skew_h``,
    exactly **one** make-up run fires on the first tick (``catch_up=True``
    on ``backup_started``).  The SECOND tick does NOT fire a second make-up
    run — the ``_catch_up_used`` guard prevents double-makeup.
    """
    monkeypatch.setattr(_cfg, "maint_backup_max_skew_h", 36)
    monkeypatch.setattr(_cfg, "maint_backup_clock_step_forward_alert_h", 240)
    clock = _StubClock(_t(2025, 3, 5, 2, 30))
    agent = _build_agent(clock=clock)

    list(agent.flush_expired())
    clock.set(_t(2025, 3, 5, 3, 0))
    list(agent.flush_expired())

    # Jump ~50h ahead (> 36h max_skew_h).
    clock.set(_t(2025, 3, 7, 5, 0))
    agent._next_fire_at = _t(2025, 3, 7, 4, 59)  # noqa: SLF001 — test
    first_tick = list(agent.flush_expired())

    started_first = next(
        (m.payload for m in first_tick if m.payload.get("kind") == "backup_started"),
        None,
    )
    assert started_first is not None, "first tick must fire a make-up run"
    assert started_first["catch_up"] is True

    # Second tick: no second make-up run (catch_up_used guard).
    agent._next_fire_at = _t(2025, 3, 7, 4, 58)  # noqa: SLF001 — test
    second_tick = list(agent.flush_expired())
    # Same-day idempotency: _last_completed_wall is today → skip entirely.
    assert not any(
        (m.payload or {}).get("kind") == "backup_started" for m in second_tick
    ), "second tick must not fire a second make-up run"
