"""Phase 8 §8.15.3 — advisory-lock hold-time guard proof tests.

The §8.15.3 binding extends ``BoundLock`` with a wall-clock acquire
timer; on release, if held longer than
``cfg.maint_advisory_lock_max_hold_ms`` (default 5000ms), the
context manager fires
``sec.alert.v1{kind=maint_advisory_lock_held_long, severity=warn}``
through the process-wide alert sink. Tests pin:

  (a) registered alert kind appears in ``KNOWN_SEC_ALERT_KINDS``;
  (b) held-too-long path fires exactly one alert with the expected
      payload shape (lock_name, lock_key, hold_ms, threshold_ms);
  (c) held-just-fine path fires no alert;
  (d) absence of a sink is silently tolerated;
  (e) threshold ``0`` disables the guard entirely.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


class _StubCursor:
    """Minimal cursor that pretends ``pg_try_advisory_lock`` always
    succeeds — the guard logic is independent of the real PG path.
    """

    def __init__(self) -> None:
        self._last_sql: str = ""

    def __enter__(self) -> "_StubCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self._last_sql = sql

    def fetchone(self) -> tuple[bool]:
        # ``True`` for try_advisory_lock; unlock returns no row.
        return (True,) if "try_advisory_lock" in self._last_sql else (None,)  # type: ignore[return-value]


class _StubConn:
    def cursor(self) -> _StubCursor:
        return _StubCursor()


def test_kind_is_registered() -> None:
    """Boundary: the new kind must be in ``KNOWN_SEC_ALERT_KINDS``
    so the SecAlertDebouncer + boundary tests recognise it."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS

    assert "maint_advisory_lock_held_long" in KNOWN_SEC_ALERT_KINDS


def test_held_too_long_fires_alert(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A hold longer than the configured threshold MUST emit one
    sec.alert.v1 with the correct subject + observed shape."""
    from xops.maint import advisory_lock as al
    from xops.maint.advisory_lock_keys import LOCK_MAINT_DLQ_REPLAY

    captured: list[tuple[str, str, str, dict]] = []

    def sink(kind: str, severity: str, subject: str, observed: dict) -> None:
        captured.append((kind, severity, subject, observed))

    al.set_alert_sink(sink)
    # Force the threshold low enough that any real sleep trips it.
    monkeypatch.setattr(al, "_resolve_max_hold_ms", lambda: 5)
    try:
        with al.BoundLock(_StubConn(), LOCK_MAINT_DLQ_REPLAY) as held:
            assert held is True
            time.sleep(0.05)  # 50ms > 5ms threshold
    finally:
        al.set_alert_sink(None)

    assert len(captured) == 1, captured
    kind, severity, subject, observed = captured[0]
    assert kind == "maint_advisory_lock_held_long"
    assert severity == "warn"
    assert subject == "LOCK_MAINT_DLQ_REPLAY"
    assert observed["lock_name"] == "LOCK_MAINT_DLQ_REPLAY"
    assert observed["lock_key"] == LOCK_MAINT_DLQ_REPLAY
    assert observed["threshold_ms"] == 5
    assert observed["hold_ms"] >= 5


def test_short_hold_does_not_fire_alert(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A hold under the threshold MUST NOT emit an alert."""
    from xops.maint import advisory_lock as al
    from xops.maint.advisory_lock_keys import LOCK_MAINT_DLQ_REPLAY

    captured: list[tuple[str, str, str, dict]] = []
    al.set_alert_sink(lambda *args: captured.append(args))  # type: ignore[arg-type]
    monkeypatch.setattr(al, "_resolve_max_hold_ms", lambda: 60_000)
    try:
        with al.BoundLock(_StubConn(), LOCK_MAINT_DLQ_REPLAY):
            pass  # immediate release
    finally:
        al.set_alert_sink(None)

    assert captured == []


def test_no_sink_is_silently_ok(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Releasing a long-held lock with NO sink registered must not
    raise — the guard degrades to a logged warning at most."""
    from xops.maint import advisory_lock as al
    from xops.maint.advisory_lock_keys import LOCK_MAINT_DLQ_REPLAY

    al.set_alert_sink(None)
    monkeypatch.setattr(al, "_resolve_max_hold_ms", lambda: 1)
    with al.BoundLock(_StubConn(), LOCK_MAINT_DLQ_REPLAY):
        time.sleep(0.01)  # trips the (very low) threshold


def test_threshold_zero_disables_guard(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """``cfg.maint_advisory_lock_max_hold_ms == 0`` disables the
    guard entirely (no alert regardless of hold duration)."""
    from xops.maint import advisory_lock as al
    from xops.maint.advisory_lock_keys import LOCK_MAINT_DLQ_REPLAY

    captured: list[tuple] = []
    al.set_alert_sink(lambda *a: captured.append(a))  # type: ignore[arg-type]
    monkeypatch.setattr(al, "_resolve_max_hold_ms", lambda: 0)
    try:
        with al.BoundLock(_StubConn(), LOCK_MAINT_DLQ_REPLAY):
            time.sleep(0.02)
    finally:
        al.set_alert_sink(None)

    assert captured == []


def test_lock_name_property() -> None:
    """The symbolic ``lock_name`` resolves through the registry so
    the alert subject is human-readable."""
    from xops.maint.advisory_lock import BoundLock
    from xops.maint.advisory_lock_keys import LOCK_MAINT_DLQ_REPLAY

    bl = BoundLock(_StubConn(), LOCK_MAINT_DLQ_REPLAY)
    assert bl.lock_name == "LOCK_MAINT_DLQ_REPLAY"
