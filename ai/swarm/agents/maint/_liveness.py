"""Phase 8 §8.10 — Liveness probe mixin for §8.x maintenance agents.

Every §8.x maintenance agent inherits :class:`LivenessMixin`.  The mixin
tracks when the :class:`~ai.swarm.sdk.runner.AgentRunner` last called
:meth:`on_heartbeat` and exposes:

* :meth:`heartbeat_age_s` — seconds since the last runner heartbeat.
* :meth:`is_alive` — ``heartbeat_age_s() < 3 × heartbeat_sec``.
* :meth:`healthz_dict` — JSON body for the Phase 14 ``/healthz`` sidecar.
* :meth:`on_heartbeat` — runner callback; records timestamp and drives
  periodic per-agent work in subclass overrides.

The HTTP ``/healthz`` sidecar (Phase 14 K8s) calls :meth:`healthz_dict`
to build its response body.  In compose mode, :func:`registry_liveness`
(used by ``make ops.liveness``) drives the same staleness check via the
:class:`~ai.swarm.sdk.registry.AgentRegistry` without needing HTTP.
"""
from __future__ import annotations

import time
from typing import Callable


class LivenessMixin:
    """Liveness probe mixin for §8.x maintenance agents.

    Agents call :meth:`_liveness_init` from their ``__init__`` (as the
    last step) to arm the clock.  The
    :class:`~ai.swarm.sdk.runner.AgentRunner` discovers
    :meth:`on_heartbeat` via duck-typing (``_has_heartbeat_tick``) and
    calls it every ``heartbeat_sec`` seconds.

    The injectable ``liveness_clock`` (default: :func:`time.monotonic`)
    makes unit tests deterministic without sleeping.
    """

    def _liveness_init(
        self,
        *,
        liveness_clock: Callable[[], float] | None = None,
    ) -> None:
        """Arm the liveness clock.  Call at the end of ``__init__``."""
        self._liveness_clock: Callable[[], float] = (
            liveness_clock if liveness_clock is not None else time.monotonic
        )
        # Initialised to *now* so a freshly-constructed agent is live.
        self._last_heartbeat_s: float = self._liveness_clock()

    def _note_heartbeat(self) -> None:
        """Record the current time as the most-recent heartbeat instant."""
        self._last_heartbeat_s = self._liveness_clock()

    def heartbeat_age_s(self) -> float:
        """Return seconds elapsed since the last runner heartbeat.

        A freshly-constructed agent returns ≈ 0.0; the value grows
        monotonically until :meth:`on_heartbeat` (or
        :meth:`_note_heartbeat`) is called again.
        """
        return self._liveness_clock() - self._last_heartbeat_s

    def is_alive(self, heartbeat_sec: int) -> bool:
        """Return ``True`` when ``heartbeat_age_s() < 3 × heartbeat_sec``.

        Mirrors the ``DEAD_BEAT_MULTIPLIER = 3`` sentinel used by
        :meth:`~ai.swarm.sdk.registry.AgentRegistry.is_stale`.
        """
        return self.heartbeat_age_s() < 3 * heartbeat_sec

    def healthz_dict(self, heartbeat_sec: int) -> dict:
        """Return the JSON body for the Phase 14 ``/healthz`` sidecar.

        Shape: ``{"alive": bool, "heartbeat_age_s": float}``.
        """
        age = self.heartbeat_age_s()
        return {
            "alive": age < 3 * heartbeat_sec,
            "heartbeat_age_s": round(age, 3),
        }

    def on_heartbeat(self) -> None:
        """Runner callback — called every ``heartbeat_sec`` seconds.

        Records the heartbeat instant.  Subclasses SHOULD call
        ``super().on_heartbeat()`` (or ``self._note_heartbeat()``
        directly) to keep the liveness clock current, and MAY add
        periodic agent-specific logic.
        """
        self._note_heartbeat()


__all__ = ["LivenessMixin"]
