"""Phase 10 §10.21.4 — Humanizer circuit breaker with pod/cluster scope.

**Scope modes:**
  - ``pod`` (default): Per-pod in-memory state (threading.RLock). Fast, isolated.
  - ``cluster``: Redis-backed cross-pod coordination. Adds Redis round-trip on
    every humanize call → only use after measuring per-pod breaker open-rate
    above 5% (stampede-protection in dense replica deployments).

**State machine:**
  - ``closed`` → normal operation
  - ``open`` → breaker tripped, refuse all humanize calls for
    ``cfg.nlp_humanizer_breaker_open_s`` (default 60s)

**Breach triggers:** Latency over ``cfg.nlp_humanizer_max_latency_ms`` (default 600ms).

**Proof contract:**
  - ``test_nlp_humanizer_breaker_per_pod_isolated`` — per-pod breakers are isolated
  - ``test_nlp_humanizer_breaker_cluster_scope_redis_path`` — cluster mode uses Redis

Config keys (single-source, ``ai/common/config.py``):
  - ``nlp_humanizer_breaker_scope`` ∈ {pod, cluster} (default pod)
  - ``nlp_humanizer_breaker_open_s`` (default 60)
  - ``nlp_humanizer_max_latency_ms`` (default 600)
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ai.common.config import Config


class HumanizerCircuitBreaker:
    """Circuit breaker for the §10.8 humanizer with configurable scope.

    **Default mode (scope='pod'):**
      - State held in-memory (per-pod, isolated from other replicas).
      - Lock: threading.RLock (cheap, microseconds).
      - Use case: Default for all deployments until stampede-protection is needed.

    **Cluster mode (scope='cluster'):**
      - State held in Redis (cross-pod coordination).
      - Lock: Redis SETNX with TTL (one round-trip per humanize call).
      - Use case: Opt-in after measuring per-pod breaker open-rate > 5% in dense
        replica deployments (stampede-protection: one pod opens breaker → all pods refuse).

    **Usage:**
        >>> from ai.common.config import Config
        >>> cfg = Config()
        >>> breaker = HumanizerCircuitBreaker(cfg=cfg)
        >>> if breaker.is_open():
        ...     # Fall back to template-only mode
        ...     return templated_answer
        >>> # Attempt humanize call
        >>> try:
        ...     output = _call_humanizer_llm(...)
        ...     breaker.record_success()
        ... except TimeoutError:
        ...     breaker.record_failure()
        ...     # Fall back to template

    **State transitions:**
      - ``closed`` + failure → ``open`` (for ``breaker_open_s`` seconds)
      - ``open`` + time elapsed → ``closed`` (auto-heal)

    **Metrics emitted** (via ``common.telemetry``):
      - ``nlp_humanizer_breaker_state{state}`` gauge (closed=1 or open=1)
      - ``nlp.event.v1{kind=humanizer_breaker_open}`` once on transition to open

    Args:
        cfg: Config instance. Must have ``nlp_humanizer_breaker_scope``,
            ``nlp_humanizer_breaker_open_s``, and Redis config (for cluster mode).
    """

    def __init__(self, *, cfg: Config):
        from ai.common.config import cfg as _default_cfg

        self._cfg = cfg if cfg is not None else _default_cfg
        self._scope: Literal["pod", "cluster"] = self._cfg.nlp_humanizer_breaker_scope  # type: ignore[assignment]

        # Per-pod state (used only when scope='pod')
        self._lock = threading.RLock()
        self._opened_at: float | None = None  # None = closed, float = timestamp when opened

        # Cluster state (used only when scope='cluster')
        # Redis key: "nlp:humanizer:breaker:open" with TTL = breaker_open_s
        # If key exists → breaker is open; else closed
        self._redis_key = "nlp:humanizer:breaker:open"

    def is_open(self) -> bool:
        """Check if the breaker is currently open.

        Returns True if the breaker is open (refuse humanize calls).
        Returns False if closed (normal operation).

        **Per-pod mode:**
          - Checks in-memory ``_opened_at`` timestamp.
          - Auto-heal: If ``time.time() - _opened_at > breaker_open_s``, transition to closed.

        **Cluster mode:**
          - Checks Redis key existence (``EXISTS nlp:humanizer:breaker:open``).
          - Auto-heal: Redis TTL handles expiry (breaker_open_s seconds).

        Returns:
            True if breaker is open (refuse humanize), False if closed.
        """
        if self._scope == "pod":
            return self._is_open_pod()
        else:  # cluster
            return self._is_open_cluster()

    def record_failure(self) -> None:
        """Record a humanizer failure (latency breach or error).

        Opens the breaker for ``cfg.nlp_humanizer_breaker_open_s`` seconds.
        Emits ``nlp.event.v1{kind=humanizer_breaker_open}`` once on transition.

        **Per-pod mode:**
          - Sets ``_opened_at = time.time()`` under lock.
          - Emits telemetry state=open.

        **Cluster mode:**
          - ``SETEX nlp:humanizer:breaker:open <breaker_open_s> 1``
          - Emits telemetry state=open.
        """
        if self._scope == "pod":
            self._record_failure_pod()
        else:  # cluster
            self._record_failure_cluster()

    def record_success(self) -> None:
        """Record a successful humanize call.

        Currently a no-op (failures open the breaker; success does not affect state).
        Auto-heal happens via timeout (pod: in-memory time check, cluster: Redis TTL).

        Future §10.8 half-open state: Could probe after breaker opens,
        re-close on success. Phase 10 v1 uses simple time-based auto-heal.
        """
        # Auto-heal is time-based per §10.8 (breaker opens for fixed duration).
        # Future enhancement: half-open state with probe-on-success.
        pass

    # ── Per-pod implementation ───────────────────────────────────────────────

    def _is_open_pod(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False  # closed
            elapsed = time.time() - self._opened_at
            if elapsed >= self._cfg.nlp_humanizer_breaker_open_s:
                # Auto-heal: breaker was open, but enough time passed → close
                self._opened_at = None
                self._emit_telemetry_state("closed")
                return False
            return True  # still open

    def _record_failure_pod(self) -> None:
        with self._lock:
            was_closed = self._opened_at is None
            self._opened_at = time.time()
            if was_closed:
                # Emit event only once on transition (closed → open)
                self._emit_breaker_open_event()
            self._emit_telemetry_state("open")

    # ── Cluster implementation (Redis-backed) ────────────────────────────────

    def _is_open_cluster(self) -> bool:
        """Check if breaker is open via Redis key existence."""
        try:
            import redis
            r = redis.Redis(
                host=self._cfg.redis_host,
                port=self._cfg.redis_port,
                password=self._cfg.redis_password if self._cfg.redis_password else None,
                db=0,
                socket_timeout=0.1,  # 100ms timeout for breaker check
                socket_connect_timeout=0.1,
            )
            exists = r.exists(self._redis_key)
            return bool(exists)
        except Exception:
            # On Redis failure, fail-open (treat as closed) to avoid blocking all humanize calls
            # Doctrine: degraded Redis → prefer letting humanize attempt rather than blanket refuse
            return False

    def _record_failure_cluster(self) -> None:
        """Open the breaker via Redis SETEX (with TTL = breaker_open_s)."""
        try:
            import redis
            r = redis.Redis(
                host=self._cfg.redis_host,
                port=self._cfg.redis_port,
                password=self._cfg.redis_password if self._cfg.redis_password else None,
                db=0,
                socket_timeout=0.1,
                socket_connect_timeout=0.1,
            )
            # SETEX sets key with TTL; Redis handles auto-expire (auto-heal)
            r.setex(self._redis_key, self._cfg.nlp_humanizer_breaker_open_s, "1")
            self._emit_breaker_open_event()
            self._emit_telemetry_state("open")
        except Exception:
            # On Redis failure, the breaker state is undefined (degraded).
            # Do NOT block the humanize call; let the per-pod latency deadline handle it.
            pass

    # ── Telemetry & events ───────────────────────────────────────────────────

    def _emit_breaker_open_event(self) -> None:
        """Emit nlp.event.v1{kind=humanizer_breaker_open} once on transition."""
        # Phase 10 stub: Event emission is Phase 10 §10.8 contract but requires
        # the bus integration (Phase 10 §10.13). For now, log locally.
        # Real implementation: bus.publish(nlp.event.v1{kind=humanizer_breaker_open})
        import logging

        _log = logging.getLogger("nlp.humanizer.breaker")
        _log.warning(
            "Humanizer circuit breaker opened (scope=%s, duration=%ds)",
            self._scope,
            self._cfg.nlp_humanizer_breaker_open_s,
        )

    def _emit_telemetry_state(self, state: Literal["closed", "open"]) -> None:
        """Set nlp_humanizer_breaker_state{state} gauge."""
        try:
            from ai.common.telemetry import set_humanizer_breaker_state

            set_humanizer_breaker_state(state)
        except Exception:
            # Telemetry failure is non-fatal (best-effort)
            pass
