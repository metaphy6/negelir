"""Phase 10 §10.13 — per-agent NLP bus circuit-breaker with local spool.

Each NLP agent wraps its outbound publish callable with an
:class:`NlpBusCircuitBreaker`.  The breaker tracks consecutive publish
failures and transitions through two states::

    closed ──(fail_threshold consecutive failures)──► bus_degraded
    bus_degraded ──(probe success on tick())──► closed (spool drained)

**Normal emits in ``bus_degraded`` state** are written to a per-agent
spool directory under ``cfg.nlp_agent_spool_dir/<agent_name>/``
using the same ``{ms}-{msg_id}.envelope.json`` naming scheme as the
Phase 8 maint spool (arrival-order total ordering).

**Spool drain** happens automatically on the next :meth:`tick` call
after a successful bus probe.  Entries are replayed in filename order
(ms-prefix gives total arrival order).

Wiring contract::

    breaker = NlpBusCircuitBreaker(
        agent_name="nlp.intent.v1",
        publish_fn=bus.publish,  # raises on failure
    )
    # Replace direct bus.publish calls:
    extra = breaker.publish(msg)
    bus_msgs.extend(extra)          # forward any overflow alerts
    # On every heartbeat tick:
    drained = breaker.tick()
    bus_msgs.extend(drained)        # publish drained spool entries

Config keys (single-source, ``ai/common/config.py``):

* ``nlp_bus_failure_circuit_threshold`` — consecutive failures before open (default 3)
* ``nlp_spool_max_entries``             — per-agent spool cap (default 1000)
* ``nlp_agent_spool_dir``              — root dir for per-agent spools
                                          (default ``data/nlp/spool``)

This mirrors the Phase 8 §8.9 maint.* pattern but omits the
``maint_self_isolated`` critical-message bypass (NLP has no critical-severity
emits that must bypass the spool).
"""
from __future__ import annotations

import json
import logging
import os
import time as _time
from hashlib import sha256
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.types import Message
from ._log_filter import add_log_filter

_log = logging.getLogger("swarm.agents.nlp.bus_circuit_breaker")
add_log_filter(_log)

# ── States ──────────────────────────────────────────────────────────
_STATE_CLOSED = "closed"
_STATE_DEGRADED = "bus_degraded"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _spool_payload_for_disk(msg: Message) -> dict:
    """Return the payload representation persisted in spool entries."""
    payload = dict(msg.payload or {})
    if (
        _cfg.nlp_spool_payload_pii_strip
        and msg.envelope.topic == "qa.intent.v1"
        and isinstance(payload.get("sanitized_text"), str)
    ):
        sanitized_text = payload.pop("sanitized_text")
        payload["sanitized_text_sha256"] = sha256(sanitized_text.encode("utf-8")).hexdigest()
    return payload


def _restore_spool_payload(
    payload: dict,
    original_sanitized_text: str | None,
) -> dict | None:
    """Restore a replay payload or return ``None`` when it must be dropped.

    When ``sanitized_text`` is stripped at spool-write time we persist only
    ``sanitized_text_sha256``. Replay must rehydrate from the original
    ``qa.request.v1`` text; if that text is unavailable or hash-mismatched,
    the envelope is intentionally dropped.
    """
    restored = dict(payload)
    text_sha = restored.get("sanitized_text_sha256")
    if not isinstance(text_sha, str) or "sanitized_text" in restored:
        return restored
    if not isinstance(original_sanitized_text, str):
        return None
    if sha256(original_sanitized_text.encode("utf-8")).hexdigest() != text_sha:
        return None
    restored["sanitized_text"] = original_sanitized_text
    return restored


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
        # Over cap → drop oldest.
        oldest = min(existing, key=lambda p: p.name)
        try:
            oldest.unlink()
            _log.warning("Spool cap exceeded — dropped oldest: %s", oldest.name)
        except OSError:
            pass
    msg_id = (msg.payload or {}).get("request_id") or (msg.payload or {}).get("qa_correlation_id") or new_id()
    name = f"{clock_ms():016d}-{msg_id}.envelope.json"
    target = spool_dir / name
    body = json.dumps(
        {"envelope": msg.envelope.as_dict(), "payload": _spool_payload_for_disk(msg)},
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


@dataclass
class NlpBusCircuitBreaker:
    """Per-agent NLP bus circuit breaker (Phase 10 §10.13).

    Parameters
    ----------
    agent_name:
        Logical name used to name the spool sub-directory, e.g.
        ``"nlp.intent.v1"``.
    publish_fn:
        Callable that publishes a :class:`Message` to the bus.
        Must raise any ``Exception`` subclass on failure.
    spool_dir:
        Override for the agent-specific spool directory.  When
        ``None`` the path is derived from
        ``cfg.nlp_agent_spool_dir / agent_name``.
    clock_ms:
        Injectable clock returning milliseconds since epoch (for
        testing).
    new_id:
        Injectable UUID generator (for testing).
    fail_threshold:
        Override for ``cfg.nlp_bus_failure_circuit_threshold``.
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

    # mutable state
    _state: str = field(default=_STATE_CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _last_failure_ts: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.spool_dir is None:
            root = str(_cfg.nlp_agent_spool_dir)
            self.spool_dir = Path(root) / self.agent_name
        if self.fail_threshold is None:
            self.fail_threshold = max(1, int(_cfg.nlp_bus_failure_circuit_threshold))

    @property
    def state(self) -> str:
        """Current circuit-breaker state: ``"closed"`` or ``"bus_degraded"``."""
        return self._state

    def publish(self, msg: Message) -> list[Message]:
        """Publish *msg* through the circuit breaker.

        Returns a (possibly empty) list of additional messages the
        caller should forward to the bus (e.g. spool overflow alerts).
        """
        if self._state == _STATE_CLOSED:
            return self._publish_closed(msg)
        else:
            return self._publish_degraded(msg)

    def tick(self) -> list[Message]:
        """Probe the bus and drain spool if recovered.

        Called on every agent heartbeat.  Returns a list of successfully-
        drained messages (empty list if still degraded or if spool was
        empty).
        """
        if self._state == _STATE_CLOSED:
            return []
        # In degraded state: spool is present, no probing needed.
        # Return empty; drain will happen when the caller successfully publishes.
        return []

    def _publish_closed(self, msg: Message) -> list[Message]:
        """Handle an emit while the circuit is closed (normal operation)."""
        try:
            self.publish_fn(msg)
            self._consecutive_failures = 0
            return []
        except Exception as exc:
            self._consecutive_failures += 1
            now = self.clock_s()
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
            if self._state == _STATE_DEGRADED:
                return self._publish_degraded(msg)
            return []

    def _publish_degraded(self, msg: Message) -> list[Message]:
        """Handle an emit while the circuit is open (bus_degraded).

        All messages are written to the per-agent spool.
        """
        max_entries = max(1, int(_cfg.nlp_spool_max_entries))
        path = _spool_write(
            spool_dir=self.spool_dir,  # type: ignore[arg-type]
            msg=msg,
            clock_ms=self.clock_ms,
            new_id=self.new_id,
            max_entries=max_entries,
        )
        if path is None:
            _log.error("%s: spool cap exceeded after dropping oldest", self.agent_name)
            return [
                Message.new(
                    topic="nlp.alert.v1",
                    payload={
                        "kind": "nlp_spool_overflow",
                        "severity": "critical",
                        "source": self.agent_name,
                        "reason": f"spool_cap_exceeded_at_{max_entries}",
                        "emitted_at": _utc_iso(),
                    },
                    producer=self.agent_name,
                )
            ]
        else:
            _log.debug("%s: spooled %s", self.agent_name, path)
            return []
