"""Phase 8 §8.10 — leader-election protocol for single-instance agents.

Most §8.x agents are bus-driven and replica-safe. Two are not:

* ``maint.scaler.v1`` — only the leader emits scale decisions.
* ``maint.dlq.v1``    — only the leader replays poisoned messages.

Until the Kubernetes lease-driver lands in Phase 14, these run with
the in-process :class:`SingleProcessLeader` which always reports
itself as the leader (the swarm boots one replica per pod by
default; horizontal scale-out for these two agents is gated on the
K8s lease implementation).

The :class:`Leader` Protocol pins the surface so the Phase 14
upgrade is a drop-in replacement; agents take a ``Leader`` in their
constructor and call ``is_leader()`` before performing leader-only
side effects.
"""
from __future__ import annotations

import threading
from typing import Protocol


class Leader(Protocol):
    """Tiny protocol the §8.2 / §8.5 leader-only loops depend on."""

    name: str

    def is_leader(self) -> bool:
        """Return True if this replica currently holds the lease."""
        ...

    def shed(self) -> None:
        """Voluntarily release leadership (e.g. on pre-shutdown
        SIGTERM). After ``shed()``, ``is_leader()`` returns False
        until the next ``acquire()``-equivalent (driver-specific)."""
        ...


class SingleProcessLeader:
    """Default in-process leader.

    Always leader unless explicitly ``shed()``-ed. Per §8.15.8 the
    shed flag is in-process state — a swarm-wide leader handoff
    requires the K8s lease driver (Phase 14).
    """

    def __init__(self, *, name: str = "single-process") -> None:
        self.name = name
        self._lock = threading.Lock()
        self._shed = False

    def is_leader(self) -> bool:
        with self._lock:
            return not self._shed

    def shed(self) -> None:
        with self._lock:
            self._shed = True

    def reacquire(self) -> None:
        """Test-only: clear a prior :meth:`shed`. Production paths
        re-acquire via the driver's lease loop."""
        with self._lock:
            self._shed = False


__all__ = ["Leader", "SingleProcessLeader"]
