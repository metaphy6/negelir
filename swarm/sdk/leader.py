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


class ControllableK8sLeader:
    """Test-harness double for a K8s coordination-lease leader.

    Simulates the real ``coordination.k8s.io/v1`` lease protocol
    without an actual API server.  The renewal loop is **explicit**
    (call :meth:`tick_renewal` from the test); the clock is
    injectable so tests can advance simulated time without sleeping.

    Lifecycle:
    * ``__init__`` grants the lease immediately (expiry = now +
      ``lease_duration_s``).
    * :meth:`tick_renewal` renews when the API is healthy; does
      nothing when :meth:`inject_api_failure` has been called.
    * :meth:`is_leader` returns True iff current clock < expiry.
    * :meth:`restore_api` re-enables renewal AND immediately renews,
      simulating the pod that wins re-election after the API comes
      back.
    * :meth:`shed` expires the lease immediately (losing pod path,
      equivalent to the K8s controller removing the Lease object).

    This class is intentionally **not** exported in ``__all__`` so
    production code cannot accidentally import it.  Test modules must
    use the full dotted name
    ``swarm.sdk.leader.ControllableK8sLeader``.
    """

    def __init__(
        self,
        *,
        name: str = "controllable-k8s",
        lease_duration_s: float = 15.0,
        clock=None,
    ) -> None:
        import time as _time

        self.name = name
        self._lease_duration_s = lease_duration_s
        self._clock = clock if clock is not None else _time.monotonic
        self._lock = threading.Lock()
        self._api_up = True
        # Grant lease at construction time.
        self._expiry: float = self._clock() + self._lease_duration_s

    # ── lease protocol ──────────────────────────────────────────

    def tick_renewal(self) -> None:
        """Renew the lease if the K8s API is healthy.

        In the real driver this fires on a background thread at
        ``renew_deadline_s`` intervals.  In tests, call it manually
        to represent an API round-trip.
        """
        with self._lock:
            if self._api_up:
                self._expiry = self._clock() + self._lease_duration_s

    def inject_api_failure(self) -> None:
        """Simulate ``coordination.k8s.io/v1`` returning 503.

        Subsequent :meth:`tick_renewal` calls silently no-op.  The
        lease will expire naturally when the clock advances past
        ``_expiry``.
        """
        with self._lock:
            self._api_up = False

    def restore_api(self) -> None:
        """Simulate the K8s API recovering.

        The first pod to call this after recovery re-acquires the
        lease immediately (models the pod that wins the post-API
        re-election).
        """
        with self._lock:
            self._api_up = True
            self._expiry = self._clock() + self._lease_duration_s

    # ── Leader protocol ─────────────────────────────────────────

    def is_leader(self) -> bool:
        with self._lock:
            return self._clock() < self._expiry

    def shed(self) -> None:
        """Immediately expire the lease (models losing pod giving up
        the lease before the K8s controller forcibly removes it)."""
        with self._lock:
            self._expiry = self._clock() - 1.0

    def reacquire(self) -> None:
        """Reacquire the lease without going through the API.
        Test-only convenience alias for :meth:`restore_api`."""
        self.restore_api()


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


#: ROADMAP §8.10 — single source of truth for the set of maint-plane
#: agent ids that **must** route every emit through a :class:`Leader`
#: gate. Two replicas of any of these agents would either double-emit
#: side-effects (scaler decisions, dlq replays, backup runs) or race
#: on shared state (sec hysteresis timer, schema-change auto-apply
#: ledger). The boundary test in
#: ``ai/swarm/agents/maint/tests/test_leader_boundary.py`` pins this
#: set against the live registry so an agent that gets renamed,
#: removed, or added without a matching update here fails CI.
LEADER_REQUIRED_AGENTS: frozenset[str] = frozenset({
    "maint.scaler.v1",
    "maint.backup.v1",
    "maint.dlq.v1",
    "maint.schema.v1",
    "maint.sec.v1",
})


__all__ = [
    "Leader",
    "SingleProcessLeader",
    "KubernetesLeader",
    "LEADER_REQUIRED_AGENTS",
    # ControllableK8sLeader is intentionally absent from __all__ so
    # production imports cannot accidentally pull it in.
]
