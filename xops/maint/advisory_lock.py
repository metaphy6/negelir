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
from typing import Any, Protocol

from .advisory_lock_keys import ALL_LOCK_KEYS

_log = logging.getLogger("xops.maint.advisory_lock")


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

    def __init__(self, conn: _PgConn, key: int) -> None:
        if key not in self._REGISTERED_VALUES:
            raise ValueError(
                f"advisory-lock key {key!r} not registered in "
                "xops.maint.advisory_lock_keys"
            )
        self._conn = conn
        self._key = int(key)
        self._held = False

    def __enter__(self) -> bool:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (self._key,))
                row = cur.fetchone()
                self._held = bool(row and row[0])
        except Exception:  # noqa: BLE001 — connection-level errors not retried
            _log.exception("advisory_lock acquire failed for key=%d", self._key)
            self._held = False
        return self._held

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._held:
            return
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (self._key,))
        except Exception:  # noqa: BLE001
            _log.exception("advisory_lock release failed for key=%d", self._key)
        finally:
            self._held = False


__all__ = ["BoundLock"]
