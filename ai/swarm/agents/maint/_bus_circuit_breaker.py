"""Phase 8 §8.9 — per-agent bus circuit-breaker with local spool.

Each maint agent wraps its outbound publish callable with a
:class:`BusCircuitBreaker`.  The breaker tracks consecutive publish
failures and transitions through two states::

    closed ──(fail_threshold consecutive failures)──► bus_degraded
    bus_degraded ──(probe success on tick())──► closed (spool drained)

**Normal emits in ``bus_degraded`` state** are written to a per-agent
spool directory under ``cfg.maint_agent_spool_dir/<agent_name>/``
using the same ``{ms}-{msg_id}.envelope.json`` naming scheme as the
opsctl spool (arrival-order total ordering).

**Critical-severity emits** bypass the spool — the breaker attempts the
publish directly.  If the attempt also fails the breaker instead
returns a ``sec.alert.v1{kind=maint_self_isolated, severity=critical}``
message to the caller (so the isolation event is visible), and marks
``self_isolated=True``.  The original critical message is NOT silently
dropped.

**Spool drain** happens automatically on the next :meth:`tick` call
after a successful bus probe.  Entries are replayed in filename order
(ms-prefix gives total arrival order).

Wiring contract::

    breaker = BusCircuitBreaker(
        agent_name="maint.scaler.v1",
        publish_fn=bus.publish,  # raises on failure
    )
    # Replace direct bus.publish calls:
    extra = breaker.publish(msg)
    bus_msgs.extend(extra)          # forward any self-isolation alerts
    # On every heartbeat tick:
    drained = breaker.tick()
    bus_msgs.extend(drained)        # publish drained spool entries

Config keys (single-source, ``ai/common/config.py``):

* ``maint_bus_fail_threshold``   — consecutive failures before open (default 3)
* ``maint_bus_spool_max_entries`` — per-agent spool cap (default 1024)
* ``maint_agent_spool_dir``      — root dir for per-agent spools
                                   (default ``data/maint/agent_spool``)
"""
from __future__ import annotations

import json
import logging
import os
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.types import Message
from ..topics import SEC_ALERT

_log = logging.getLogger("swarm.agents.maint.bus_circuit_breaker")

# ── States ──────────────────────────────────────────────────────────
_STATE_CLOSED = "closed"
_STATE_DEGRADED = "bus_degraded"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _is_critical(msg: Message) -> bool:
    """Return True if *msg* carries ``severity=critical`` in its payload."""
    payload = msg.payload or {}
    return str(payload.get("severity", "")).lower() == "critical"


def _spool_write(
    spool_dir: Path,
    msg: Message,
    clock_ms: Callable[[], int],
    new_id: Callable[[], str],
    max_entries: int,
) -> str | None:
    """Write *msg* to spool.  Returns file path or None if cap exceeded."""
    spool_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    existing = list(spool_dir.glob("*.envelope.json"))
    if len(existing) >= max_entries:
        return None
    msg_id = (msg.payload or {}).get("request_id") or new_id()
    name = f"{clock_ms():016d}-{msg_id}.envelope.json"
    target = spool_dir / name
    body = json.dumps(
        {"envelope": msg.envelope.as_dict(), "payload": msg.payload or {}},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    return str(target)


def _spool_read_ordered(spool_dir: Path) -> list[Path]:
    """Return spool entries sorted by filename (arrival order)."""
    return sorted(spool_dir.glob("*.envelope.json"))


def _load_message(path: Path) -> Message | None:
    """Deserialise a spool entry.  Returns None on malformed JSON."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
        from ...sdk.types import Envelope

        env = Envelope(**data["envelope"])
        return Message(envelope=env, payload=data.get("payload") or {})
    except Exception:  # noqa: BLE001 — malformed file, treat as unrecoverable
        return None


@dataclass
class BusCircuitBreaker:
    """Per-agent bus circuit breaker (Phase 8 §8.9).

    Parameters
    ----------
    agent_name:
        Logical name used to name the spool sub-directory, e.g.
        ``"maint.scaler.v1"``.
    publish_fn:
        Callable that publishes a :class:`Message` to the bus.
        Must raise any ``Exception`` subclass on failure.
    spool_dir:
        Override for the agent-specific spool directory.  When
        ``None`` the path is derived from
        ``cfg.maint_agent_spool_dir / agent_name``.
    clock_ms:
        Injectable clock returning milliseconds since epoch (for
        testing).
    new_id:
        Injectable UUID generator (for testing).
    fail_threshold:
        Override for ``cfg.maint_bus_fail_threshold``.
    """

    agent_name: str
    publish_fn: Callable[[Message], None]
    spool_dir: Path | None = None
    clock_ms: Callable[[], int] = field(
        default_factory=lambda: lambda: int(_time.time() * 1000)
    )
    clock_s: Callable[[], float] = field(
        default_factory=lambda: _time.monotonic
    )
    new_id: Callable[[], str] = field(default_factory=lambda: _new_id)
    fail_threshold: int | None = None
    fail_window_s: float | None = None

    # mutable state
    _state: str = field(default=_STATE_CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _last_failure_ts: float | None = field(default=None, init=False)
    self_isolated: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.spool_dir is None:
            root = str(_cfg.maint_agent_spool_dir)
            self.spool_dir = Path(root) / self.agent_name
        if self.fail_threshold is None:
            self.fail_threshold = max(1, int(_cfg.maint_bus_fail_threshold))
        if self.fail_window_s is None:
            self.fail_window_s = max(1.0, float(_cfg.maint_bus_fail_window_s))

    # ── Public interface ────────────────────────────────────────────

    @property
    def state(self) -> str:
        """Current circuit-breaker state: ``"closed"`` or ``"bus_degraded"``."""
        return self._state

    def publish(self, msg: Message) -> list[Message]:
        """Publish *msg* through the circuit breaker.

        Returns a (possibly empty) list of additional messages the
        caller should forward to the bus (e.g. self-isolation alerts).
        """
        if self._state == _STATE_CLOSED:
            return self._publish_closed(msg)
        else:
            return self._publish_degraded(msg)

    def tick(self) -> list[Message]:
        """Probe bus when degraded; drain spool on recovery.

        Returns messages that were successfully re-published from the
        spool (callers do NOT need to re-publish these — they have
        already been sent through ``publish_fn``).  Returns empty list
        when the breaker is in ``closed`` state.
        """
        if self._state != _STATE_DEGRADED:
            return []
        # Probe — try publishing an empty heartbeat-style payload to
        # verify the bus is reachable.  We do NOT use the spool entries
        # for the probe because a failed probe must not consume them.
        probe = Message.new(
            topic=SEC_ALERT,
            payload={
                "kind": "bus_probe",
                "severity": "info",
                "source": f"{self.agent_name}.circuit_breaker",
                "ts": _utc_iso(),
            },
            producer=self.agent_name,
        )
        try:
            self.publish_fn(probe)
        except Exception:
            _log.debug(
                "%s: bus probe failed — staying bus_degraded", self.agent_name
            )
            return []

        # Probe succeeded → recover and drain spool in arrival order.
        self._state = _STATE_CLOSED
        self._consecutive_failures = 0
        self.self_isolated = False
        _log.info("%s: bus recovered — draining spool", self.agent_name)
        return self._drain_spool()

    # ── Internals ───────────────────────────────────────────────────

    def _publish_closed(self, msg: Message) -> list[Message]:
        """Attempt publish in closed state; on failure count and possibly open."""
        try:
            self.publish_fn(msg)
            self._consecutive_failures = 0
            self._last_failure_ts = None
            return []
        except Exception as exc:
            now = self.clock_s()
            # Reset streak if the previous failure was outside the window.
            if (
                self._last_failure_ts is not None
                and now - self._last_failure_ts > self.fail_window_s  # type: ignore[operator]
            ):
                self._consecutive_failures = 0
            self._consecutive_failures += 1
            self._last_failure_ts = now
            _log.warning(
                "%s: publish failure %d/%d: %s",
                self.agent_name,
                self._consecutive_failures,
                self.fail_threshold,
                exc,
            )
            if self._consecutive_failures >= self.fail_threshold:
                self._state = _STATE_DEGRADED
                _log.error(
                    "%s: bus_degraded after %d consecutive failures",
                    self.agent_name,
                    self._consecutive_failures,
                )
            # The message that failed to publish must also be spooled
            # (unless it is critical — handled by the degraded path).
            if self._state == _STATE_DEGRADED:
                return self._publish_degraded(msg)
            return []

    def _publish_degraded(self, msg: Message) -> list[Message]:
        """Handle an emit while the circuit is open (bus_degraded).

        Critical-severity messages bypass the spool — they are attempted
        directly, and on second failure produce ``maint_self_isolated``.
        Normal messages are written to the per-agent spool.
        """
        if _is_critical(msg):
            return self._publish_critical_degraded(msg)
        # Non-critical → spool.
        max_entries = max(1, int(_cfg.maint_agent_spool_max_entries))
        path = _spool_write(
            spool_dir=self.spool_dir,  # type: ignore[arg-type]
            msg=msg,
            clock_ms=self.clock_ms,
            new_id=self.new_id,
            max_entries=max_entries,
        )
        if path is None:
            _log.error("%s: spool cap exceeded — dropping non-critical emit", self.agent_name)
        else:
            _log.debug("%s: spooled %s", self.agent_name, path)
        return []

    def _publish_critical_degraded(self, msg: Message) -> list[Message]:
        """Attempt a critical message directly; on failure emit maint_self_isolated."""
        try:
            self.publish_fn(msg)
            return []
        except Exception as exc:
            _log.error(
                "%s: critical emit failed during bus outage: %s — self-isolating",
                self.agent_name,
                exc,
            )
            self.self_isolated = True
            return [
                Message.new(
                    topic=SEC_ALERT,
                    payload={
                        "kind": "maint_self_isolated",
                        "severity": "critical",
                        "source": self.agent_name,
                        "reason": "critical_emit_failed_during_bus_outage",
                        "ts": _utc_iso(),
                    },
                    producer=self.agent_name,
                )
            ]

    def _drain_spool(self) -> list[Message]:
        """Replay spool entries in arrival order via publish_fn.

        Successfully published entries are unlinked.  On any failure
        the drain stops (the remaining entries stay for the next tick).
        Returns the list of successfully-drained messages.
        """
        assert self.spool_dir is not None
        drained: list[Message] = []
        for path in _spool_read_ordered(self.spool_dir):
            msg = _load_message(path)
            if msg is None:
                malformed = path.with_suffix(".malformed")
                path.rename(malformed)
                _log.warning("%s: malformed spool entry renamed to %s", self.agent_name, malformed)
                continue
            try:
                self.publish_fn(msg)
                path.unlink(missing_ok=True)
                drained.append(msg)
            except Exception as exc:
                _log.warning(
                    "%s: spool drain publish failed (%s) — stopping drain",
                    self.agent_name,
                    exc,
                )
                # Bus went down again mid-drain → re-open the breaker.
                self._state = _STATE_DEGRADED
                self._consecutive_failures = 1
                break
        return drained


__all__ = ["BusCircuitBreaker"]
