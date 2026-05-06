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


class KubernetesLeader:
    """Placeholder lease-driver for the Phase 14 Kubernetes deploy.

    The real driver will use ``coordination.k8s.io/v1.Lease`` with
    the parameters pinned in ROADMAP §8.10 (15s lease duration,
    10s renew deadline, 5s retry period). Until Phase 14 lands the
    Kubernetes client + ServiceAccount + RBAC, instantiating this
    class **refuses loud** rather than silently noop-ing — a
    misconfigured ``cfg.maint_runtime=k8s`` environment that bypassed
    the bootstrap selector should not produce a "leader" that is
    actually no one (mirrors the ``ComposeController`` /
    ``K8sController`` selector discipline in §8.2).

    Test harnesses must use :class:`SingleProcessLeader`. The Phase
    14 patch will replace the body of ``__init__`` with the real
    lease loop and remove this docstring's "stub" wording.
    """

    name: str

    def __init__(
        self,
        *,
        name: str,
        namespace: str = "negelir",
        lease_duration_s: int = 15,
        renew_deadline_s: int = 10,
        retry_period_s: int = 5,
    ) -> None:
        self.name = name
        self._namespace = namespace
        self._lease_duration_s = lease_duration_s
        self._renew_deadline_s = renew_deadline_s
        self._retry_period_s = retry_period_s
        raise NotImplementedError(
            "KubernetesLeader is a Phase 14 stub. "
            "Use SingleProcessLeader in compose / tests; the K8s "
            "lease driver lands with the Phase 14 deploy package."
        )

    def is_leader(self) -> bool:  # pragma: no cover - unreachable
        raise NotImplementedError

    def shed(self) -> None:  # pragma: no cover - unreachable
        raise NotImplementedError


__all__ = ["Leader", "SingleProcessLeader", "KubernetesLeader"]
