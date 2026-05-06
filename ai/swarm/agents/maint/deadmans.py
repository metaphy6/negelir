"""Phase 8 §8.16 D2 — dead-mans-switch for the maintenance plane.

The bootstrap loop calls :meth:`MaintDeadmansSwitch.tick` on a timer
(once a minute is plenty). The switch:

1. Tracks the wall-clock timestamp of the last observed
   ``maint.event.v1`` message. If silence exceeds
   ``cfg.maint_silence_alert_h`` hours AND swarm uptime exceeds
   ``cfg.maint_silence_warmup_s`` seconds, it emits one critical
   ``sec.alert.v1{kind=maint_silence_alert}`` per
   ``cfg.maint_silence_dedup_s`` window.

2. Inspects each registered maint.* agent's *self*-DLQ depth. When
   any agent's depth crosses ``cfg.maint_self_dlq_alert``, the
   switch flips that agent's :class:`PauseState.self_isolated` to
   True (the agent then refuses ``maint_pause`` per §8.13.5 until
   an operator explicitly resumes it) and emits a critical
   ``sec.alert.v1{kind=maint_self_dlq_alert}`` once per dedup
   window.

The switch carries no data-plane authority — it only observes and
emits alerts. The actual self-isolation effect is achieved through
the shared :class:`PauseState` (see ``_pause_state.py``).

Wiring contract for the bootstrap loop:

* Subscribe to ``maint.event.v1`` and call :meth:`note_event` on
  every received message.
* Periodically call :meth:`tick(now_s, dlq_depths)` where
  ``dlq_depths`` is ``{agent_id: depth}``.
* Forward returned messages to the bus.
* Construct with ``agents={agent_id: agent_instance}`` so the
  switch can mutate the agents' :class:`PauseState`.
"""

from __future__ import annotations

import secrets
import time as _time
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol

from common.config import cfg as _cfg
from ...sdk.types import Message
from ..topics import SEC_ALERT


class _HasPause(Protocol):
    name: str

    @property
    def _pause(self): ...  # type: ignore[no-untyped-def]


def _utc_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _DedupSlot:
    last_emit_s: float = 0.0


@dataclass
class MaintDeadmansSwitch:
    """Phase 8 §8.16 D2 dead-mans-switch."""

    agents: Mapping[str, _HasPause] = field(default_factory=dict)
    started_at_s: float = field(default_factory=lambda: _time.time())
    last_event_s: float | None = None  # None until we observe one

    # Per-(kind, subject) dedup so we don't spam.
    _dedup: dict[tuple[str, str], _DedupSlot] = field(default_factory=dict)

    name: str = "maint.deadmans.v1"  # for sec.alert.source field

    # ── Inputs from the bootstrap loop ───────────────────────────
    def note_event(self, *, now_s: float | None = None) -> None:
        """Call once per received ``maint.event.v1`` message."""
        self.last_event_s = _time.time() if now_s is None else now_s

    def tick(self, *, now_s: float | None = None,
             dlq_depths: Mapping[str, int] | None = None) -> list[Message]:
        """Run the dead-mans-switch checks and return alerts to publish."""
        now = _time.time() if now_s is None else now_s
        out: list[Message] = []
        out.extend(self._check_silence(now))
        out.extend(self._check_self_dlq(now, dlq_depths or {}))
        return out

    # ── Detectors ────────────────────────────────────────────────
    def _check_silence(self, now_s: float) -> Iterable[Message]:
        warmup_s = max(60, int(_cfg.maint_silence_warmup_s))
        if now_s - self.started_at_s < warmup_s:
            return ()
        threshold_s = max(3600, int(_cfg.maint_silence_alert_h) * 3600)
        # If we've never seen one, the silence age is uptime.
        last = self.last_event_s if self.last_event_s is not None else self.started_at_s
        silence_s = now_s - last
        if silence_s < threshold_s:
            return ()
        if not self._should_emit("maint_silence_alert", "global", now_s):
            return ()
        return (self._alert(
            kind="maint_silence_alert",
            severity="critical",
            reason=(f"no maint.event.v1 observed for {int(silence_s)}s "
                    f"(threshold {threshold_s}s)"),
            subject=None,
        ),)

    def _check_self_dlq(self, now_s: float,
                        dlq_depths: Mapping[str, int]) -> Iterable[Message]:
        threshold = max(1, int(_cfg.maint_self_dlq_alert))
        for agent_id, depth in dlq_depths.items():
            if depth < threshold:
                continue
            agent = self.agents.get(agent_id)
            if agent is not None:
                # Flip self-isolation. The agent's _handle_pause will
                # then refuse maint_pause until an operator resumes.
                try:
                    agent._pause.self_isolated = True
                except AttributeError:
                    # Agent doesn't expose a PauseState — skip the
                    # mutation but still emit the alert so an
                    # operator notices.
                    pass
            if not self._should_emit("maint_self_dlq_alert", agent_id, now_s):
                continue
            yield self._alert(
                kind="maint_self_dlq_alert",
                severity="critical",
                reason=(f"self-DLQ depth {depth} >= threshold {threshold} "
                        f"for {agent_id}"),
                subject=agent_id,
            )

    # ── Helpers ──────────────────────────────────────────────────
    def _should_emit(self, kind: str, subject: str, now_s: float) -> bool:
        dedup_s = max(1, int(_cfg.maint_silence_dedup_s))
        slot = self._dedup.setdefault((kind, subject), _DedupSlot())
        if now_s - slot.last_emit_s < dedup_s:
            return False
        slot.last_emit_s = now_s
        return True

    def _alert(self, *, kind: str, severity: str, reason: str,
               subject: str | None) -> Message:
        alert_id = secrets.token_hex(8)
        payload = {
            "alert_id": alert_id,
            "kind": kind,
            "severity": severity,
            "source": "maint.deadmans.v1",
            "reason": reason[:1024],
            "subject": subject,
            "request_id": None,
            "client_id": None,
            "ip": None,
            "evidence_ref": None,
            "produced_at": _utc_iso(),
        }
        return Message.new(SEC_ALERT, payload, producer=self.name)


__all__ = ["MaintDeadmansSwitch"]
