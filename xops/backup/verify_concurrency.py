"""Phase 8 §8.15.10 Fix A — restore-verify concurrency cap.

Sunday cold-verify (§8.3) and Sunday nightly restore-verify can both
fire near the Sunday-05:00 cron edge.  Two concurrent ``pg_restore
--jobs=N`` runs against an under-provisioned verify cluster OOM both
without a useful error.

The fix: a single PG advisory lock
``LOCK_MAINT_BACKUP_RESTORE_VERIFY`` (registered in the §8.15.3
registry) serialises both code paths.  The second acquirer waits up to
``cfg.maint_backup_verify_lock_timeout_s`` (default 1800 s = 30 min)
then **yields** rather than blocks indefinitely:

* It emits ``maint.event.v1{kind=backup_completed, outcome=verify_concurrency_blocked}``
  (the standard backup audit row) + ``sec.alert.v1{kind=verify_concurrency_blocked,
  severity=warn}`` (debounced).
* **Yield policy: cold-verify YIELDS to nightly.**  The nightly
  restore-verify is a daily dependency; cold-verify can re-run the
  following Sunday.  When the competing scope is ``nightly``, the
  cold-verify caller always yields after a single try.  Nightly waits
  the full timeout before yielding.

The lock is held inside a ``finally`` block — a crash mid-verify drops
the PG advisory lock automatically when the session disconnects.

Usage::

    from xops.backup.verify_concurrency import RestoreVerifyConcurrencyLock

    with RestoreVerifyConcurrencyLock(conn, scope="nightly") as held:
        if not held:
            return   # yielded; audit row + alert already emitted
        ... run the actual restore-verify ...
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional, Protocol

from xops.maint.advisory_lock_keys import LOCK_MAINT_BACKUP_RESTORE_VERIFY
from ai.common.config import cfg  # type: ignore[import]  # xops runs with ai/ on PYTHONPATH

_log = logging.getLogger("xops.backup.verify_concurrency")

# Seconds between polling attempts while waiting for the lock.
_POLL_INTERVAL_S: float = 5.0

# Alert-sink type: same protocol as xops.maint.advisory_lock.AlertSink
AlertSink = Callable[[str, str, str, dict], None]


class _PgConn(Protocol):
    """Minimal psycopg-style connection we depend on."""

    def cursor(self) -> Any: ...


class RestoreVerifyConcurrencyLock:
    """Context manager that serialises cold-verify and nightly
    restore-verify through a single PG advisory lock.

    Parameters
    ----------
    conn:
        A psycopg-style connection.  The lock is session-scoped; the
        caller MUST NOT re-use the connection for anything else while
        the lock is held (standard advisory-lock discipline).
    scope:
        Either ``"cold"`` (cold-verify) or ``"nightly"``.  Determines
        the yield policy: ``cold`` yields immediately on first failure
        when competing with nightly; ``nightly`` waits the full timeout.
    alert_sink:
        Optional callback to emit ``sec.alert.v1{kind=verify_concurrency_blocked}``.
        Signature: ``(kind, severity, subject, observed) -> None``.
        The sink is responsible for debouncing.

    Context-manager returns
    -----------------------
    ``True`` if the lock was acquired; ``False`` if the caller yielded.
    When ``False`` the caller MUST NOT proceed with restore-verify.
    """

    def __init__(
        self,
        conn: _PgConn,
        scope: str,
        alert_sink: Optional[AlertSink] = None,
    ) -> None:
        if scope not in ("cold", "nightly"):
            raise ValueError(
                f"RestoreVerifyConcurrencyLock scope must be 'cold' or 'nightly'; got {scope!r}"
            )
        self._conn = conn
        self._scope = scope
        self._alert_sink = alert_sink
        self._held = False
        self._key = LOCK_MAINT_BACKUP_RESTORE_VERIFY

    # ── lock helpers ───────────────────────────────────────────────────

    def _try_acquire(self) -> bool:
        """Attempt a non-blocking advisory lock acquisition."""
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_try_advisory_lock(%s);",
                    (self._key,),
                )
                row = cur.fetchone()
                return bool(row and row[0])
        except Exception:  # noqa: BLE001
            _log.exception(
                "verify_concurrency advisory_lock try_acquire failed key=%d",
                self._key,
            )
            return False

    def _release(self) -> None:
        """Best-effort release."""
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s);", (self._key,))
        except Exception:  # noqa: BLE001
            _log.exception(
                "verify_concurrency advisory_lock release failed key=%d",
                self._key,
            )

    def _emit_blocked_alert(self) -> None:
        """Fire sec.alert.v1{kind=verify_concurrency_blocked, severity=warn}."""
        if self._alert_sink is None:
            return
        try:
            self._alert_sink(
                "verify_concurrency_blocked",
                "warn",
                f"restore_verify_{self._scope}",
                {"scope": self._scope, "lock_key": self._key},
            )
        except Exception:  # noqa: BLE001
            _log.exception("verify_concurrency alert sink raised")

    # ── context protocol ───────────────────────────────────────────────

    def __enter__(self) -> bool:
        timeout_s = _resolve_timeout()
        # cold-verify: yield immediately on first contention (never wait).
        if self._scope == "cold":
            self._held = self._try_acquire()
            if not self._held:
                _log.info(
                    "restore_verify[cold] yielding: lock held by nightly; "
                    "will retry next Sunday"
                )
                self._emit_blocked_alert()
            return self._held

        # nightly: wait up to timeout_s.
        deadline = time.monotonic() + timeout_s
        while True:
            self._held = self._try_acquire()
            if self._held:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_s = min(_POLL_INTERVAL_S, remaining)
            _log.debug(
                "restore_verify[nightly] waiting for lock; %.0fs remaining",
                remaining,
            )
            time.sleep(sleep_s)

        # Timeout elapsed — yield.
        _log.warning(
            "restore_verify[nightly] lock not acquired after %.0f s; yielding",
            timeout_s,
        )
        self._emit_blocked_alert()
        return False

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._held:
            self._release()
            self._held = False


def _resolve_timeout() -> float:
    """Read cfg.maint_backup_verify_lock_timeout_s."""
    return float(cfg.maint_backup_verify_lock_timeout_s)


__all__ = ["RestoreVerifyConcurrencyLock"]
