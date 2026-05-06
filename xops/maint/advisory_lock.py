"""Phase 8 §8.15.3 — context manager around Postgres advisory locks.

The maintenance plane uses Postgres advisory locks (rather than
Redis SET NX) for cross-pod coordination because:

* The audit log + pattern_allowlist + scaler rosters live in
  Postgres anyway (one fewer dependency to fail).
* Advisory locks auto-release when the holding session disconnects —
  a crashed sweeper does not orphan its lock.

Usage::

    from xops.maint.advisory_lock import BoundLock
    from xops.maint.advisory_lock_keys import LOCK_MAINT_DLQ_REPLAY

    with BoundLock(conn, LOCK_MAINT_DLQ_REPLAY) as held:
        if not held:
            return  # someone else is replaying
        ...

The context manager swallows acquisition failure (returns ``False``);
release is best-effort and a no-op when not held. Designed to be
trivially mockable in tests via the ``connection`` Protocol below.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional, Protocol

from .advisory_lock_keys import ALL_LOCK_KEYS

_log = logging.getLogger("xops.maint.advisory_lock")


# Optional process-wide alert sink. Tests inject; production wires
# through the bus producer in the bootstrap loop. Signature:
#   sink(kind: str, severity: str, subject: str, observed: dict)
# The sink itself is responsible for debouncing.
AlertSink = Callable[[str, str, str, dict], None]
_alert_sink: Optional[AlertSink] = None


def set_alert_sink(sink: Optional[AlertSink]) -> None:
    """Register/clear the process-wide sec.alert.v1 sink for the
    §8.15.3 hold-time guard. Pass ``None`` to disable.
    """
    global _alert_sink
    _alert_sink = sink


def _resolve_max_hold_ms() -> int:
    """Read ``cfg.maint_advisory_lock_max_hold_ms`` lazily so test
    overrides land without re-importing the module. Falls back to
    the documented default (5000ms) on any import / attr error.
    """
    try:
        from ai.common.config import cfg  # type: ignore
        val = int(getattr(cfg, "maint_advisory_lock_max_hold_ms", 5000))
        return val if val >= 0 else 5000
    except Exception:  # noqa: BLE001 — never block release on cfg lookup
        return 5000


class _PgConn(Protocol):
    """Minimal psycopg-style connection slice we depend on."""

    def cursor(self) -> Any: ...


class BoundLock:
    """Per-call, session-scoped advisory lock.

    Use as a context manager. The boolean returned by ``__enter__``
    indicates whether the lock was actually acquired — never raises
    on contention.

    Per §8.15.3 binding the key MUST be a value registered in
    :mod:`xops.maint.advisory_lock_keys`; an unregistered key raises
    :class:`ValueError` so a typo cannot silently take a lock that
    coincides with an unrelated one.
    """

    _REGISTERED_VALUES: frozenset[int] = frozenset(ALL_LOCK_KEYS.values())
    _NAME_BY_VALUE: dict[int, str] = {v: k for k, v in ALL_LOCK_KEYS.items()}

    def __init__(self, conn: _PgConn, key: int) -> None:
        if key not in self._REGISTERED_VALUES:
            raise ValueError(
                f"advisory-lock key {key!r} not registered in "
                "xops.maint.advisory_lock_keys"
            )
        self._conn = conn
        self._key = int(key)
        self._held = False
        self._acquired_at_ns: int = 0

    @property
    def lock_name(self) -> str:
        """Symbolic name for the bound key (used in the §8.15.3
        hold-time-exceeded alert subject)."""
        return self._NAME_BY_VALUE.get(self._key, f"unregistered:{self._key}")

    def __enter__(self) -> bool:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (self._key,))
                row = cur.fetchone()
                self._held = bool(row and row[0])
        except Exception:  # noqa: BLE001 — connection-level errors not retried
            _log.exception("advisory_lock acquire failed for key=%d", self._key)
            self._held = False
        if self._held:
            self._acquired_at_ns = time.monotonic_ns()
        return self._held

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._held:
            return
        # Compute hold time before releasing so the unlock latency
        # itself does not pollute the measurement.
        hold_ms = max(
            0, int((time.monotonic_ns() - self._acquired_at_ns) // 1_000_000)
        )
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (self._key,))
        except Exception:  # noqa: BLE001
            _log.exception("advisory_lock release failed for key=%d", self._key)
        finally:
            self._held = False
            self._acquired_at_ns = 0
        # §8.15.3 — fire the hold-time guard. Threshold of 0 disables
        # the check; a missing sink is silently OK (compose-mode unit
        # tests typically run without a registered emitter).
        threshold_ms = _resolve_max_hold_ms()
        if threshold_ms > 0 and hold_ms > threshold_ms and _alert_sink is not None:
            try:
                _alert_sink(
                    "maint_advisory_lock_held_long",
                    "warn",
                    self.lock_name,
                    {
                        "lock_name": self.lock_name,
                        "lock_key": self._key,
                        "hold_ms": hold_ms,
                        "threshold_ms": threshold_ms,
                    },
                )
            except Exception:  # noqa: BLE001 — alerts must never break release
                _log.exception(
                    "advisory_lock hold-time alert sink raised for %s",
                    self.lock_name,
                )


__all__ = ["AlertSink", "BoundLock", "set_alert_sink"]
