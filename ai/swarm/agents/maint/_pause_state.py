"""Phase 8 §8.13.5 — shared pause/resume idempotency state.

Used by every ``maint.*`` agent that subscribes to ``maint_pause`` /
``maint_resume`` so the operator-facing ack matrix is consistent
across the maintenance plane.

The matrix (see :mod:`ai.swarm.agents.maint` design doc §8.13.5):

  ┌──────────────────────────────────────────────────────────────┐
  │ command         current state         accepted    reason     │
  ├──────────────────────────────────────────────────────────────┤
  │ maint_pause     running               True        paused     │
  │ maint_pause     already paused        True        already_   │
  │                                                  paused      │
  │ maint_pause     self_isolated         False       requires_  │
  │                                                  resume_first│
  │ maint_resume    paused                True        resumed    │
  │ maint_resume    already running       True        already_   │
  │                                                  resumed     │
  │ maint_resume    self_isolated         True        resumed    │
  │                                                  (clears     │
  │                                                  isolation)  │
  └──────────────────────────────────────────────────────────────┘

A re-pause that arrives with a longer TTL **widens** the deadline; a
shorter TTL is ignored (refresh-only-widens contract).

`_self_isolated` is set externally by the §8.16 dead-mans-switch
hook in the telemetry agent (Phase 8 D2) when an agent's own
self-DLQ depth crosses ``cfg.maint_self_dlq_alert``. The agent then
refuses ``maint_pause`` until an operator explicitly resumes it
(which re-enables it after the operator has investigated).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class PauseAckResult(NamedTuple):
    accepted: bool
    reason: str
    paused: bool                 # post-state
    self_isolated: bool          # post-state
    deadline_ns: int | None      # auto-resume deadline, None if running


@dataclass
class PauseState:
    """Mutable pause/isolation state for a single ``maint.*`` agent.

    The agent owns one instance and routes ``maint_pause`` /
    ``maint_resume`` through :meth:`apply_pause` / :meth:`apply_resume`.
    The returned :class:`PauseAckResult` carries the ack reason the
    agent should surface back to the operator.
    """

    paused: bool = False
    self_isolated: bool = False
    deadline_ns: int | None = None

    def apply_pause(self, *, ttl_s: int, now_ns: int) -> PauseAckResult:
        """Apply a ``maint_pause`` command and return the ack result.

        Refuses with ``requires_resume_first`` while the agent is
        self-isolated. If already paused, widens the deadline only
        when the new TTL would extend it.
        """
        if self.self_isolated:
            return PauseAckResult(False, "requires_resume_first",
                                  self.paused, self.self_isolated,
                                  self.deadline_ns)
        new_deadline = now_ns + max(1, int(ttl_s)) * 1_000_000_000
        if self.paused:
            if self.deadline_ns is None or new_deadline > self.deadline_ns:
                self.deadline_ns = new_deadline
            return PauseAckResult(True, "already_paused", True,
                                  self.self_isolated, self.deadline_ns)
        self.paused = True
        self.deadline_ns = new_deadline
        return PauseAckResult(True, "paused", True,
                              self.self_isolated, self.deadline_ns)

    def apply_resume(self) -> PauseAckResult:
        """Apply a ``maint_resume`` command and return the ack result.

        Always succeeds. Clears self-isolation if set (per §8.13.5:
        a resume after isolation is the operator's explicit re-arm).
        """
        was_running = (not self.paused) and (not self.self_isolated)
        self.paused = False
        self.deadline_ns = None
        was_isolated = self.self_isolated
        self.self_isolated = False
        if was_running:
            return PauseAckResult(True, "already_resumed", False, False, None)
        if was_isolated:
            return PauseAckResult(True, "resumed_from_isolation",
                                  False, False, None)
        return PauseAckResult(True, "resumed", False, False, None)

    def expire_if_due(self, now_ns: int) -> bool:
        """Auto-resume when the TTL deadline has passed. Returns True
        iff the state transitioned from paused → running. Self-
        isolation is not affected by TTL."""
        if (self.paused and self.deadline_ns is not None
                and now_ns >= self.deadline_ns):
            self.paused = False
            self.deadline_ns = None
            return True
        return False


__all__ = ["PauseState", "PauseAckResult"]
