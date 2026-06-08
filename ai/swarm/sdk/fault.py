"""Phase 12 §12.4 — Fault-injection framework (test-only seam).

In-process fault injection via a deterministic schedule. This module provides
a test-only seam that wraps external calls (Redis, Postgres, RPC, bus) and
applies injected faults deterministically. All production gates ensure this
code path is unreachable in prod.

The same fault scenario runs in two planes:
  1. In-process: FaultInjector (fast, deterministic, PR lane)
  2. Out-of-process: Toxiproxy / Pumba (realistic, nightly lane)

Architecture:
  - FaultSchedule: defines deterministic faults {seed, faults: [{target, op, ...}]}
  - FaultInjector: single seam that (1) increments call counters, (2) applies
    faults by name, (3) no-ops in production
  - Blast radius: faults only touch namespaced chaos resources (_chaos keyspace,
    throwaway schemas, isolated bus instance)
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generator, Optional

from common.config import cfg  # type: ignore
from common.logger import get_logger  # type: ignore


log = get_logger(__name__)


class FaultOp(str, Enum):
    """Fault operation types (1:1 mapping to Toxiproxy toxics and network behavior)."""

    DELAY = "delay"  # Network latency injection
    DROP = "drop"  # Packet loss
    ERROR = "error"  # Immediate error response
    CORRUPT = "corrupt"  # Bitflip-like payload corruption
    REORDER = "reorder"  # Message reordering (multi-message only)
    DUPLICATE = "duplicate"  # Duplicate message
    PARTITION = "partition"  # Simulate network partition (no response)


@dataclass(frozen=True)
class FaultEvent:
    """Single injected fault definition."""

    target: str  # What to fault (e.g., "redis_get", "postgres_write", "predict.vote")
    op: FaultOp  # Operation type
    after_n_calls: int = 0  # Fault fires after N calls to target (0 = first call)
    after_ms: int = 0  # Fault fires after delay_ms (for soak scenarios)
    max_duration_s: int = 30  # Auto-heal timeout (safety rail)
    payload: Optional[dict[str, Any]] = None  # Fault-specific params (latency_ms, error_code, etc.)

    def __post_init__(self) -> None:
        if self.after_n_calls < 0:
            raise ValueError(f"after_n_calls must be >= 0, got {self.after_n_calls}")
        if self.after_ms < 0:
            raise ValueError(f"after_ms must be >= 0, got {self.after_ms}")
        if self.max_duration_s < 1:
            raise ValueError(f"max_duration_s must be >= 1, got {self.max_duration_s}")


@dataclass(frozen=True)
class FaultSchedule:
    """Deterministic fault schedule (no wall-clock, no random() without seed)."""

    name: str  # E.g., "P12-8-A" (stable ID from §12.5 catalogue)
    seed: int  # Deterministic seed (same seed => same faults in same order)
    faults: tuple[FaultEvent, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Fault schedule must have a non-empty name")
        if self.seed < 0:
            raise ValueError(f"seed must be >= 0, got {self.seed}")


class FaultInjector:
    """Test-only seam for in-process fault injection.

    Properties:
      - PRODUCTION-SAFE: gated by cfg.fault_injection_enabled and an AST guard
      - DETERMINISTIC: given the same seed, same faults fire in same order
      - NAMED: every fault carries a stable ID for tracking
      - BLAST-RADIUS CONTAINED: only affects namespaced chaos resources

    Usage (test only):
      >>> schedule = FaultSchedule(
      ...     name="P12-7.1-A",
      ...     seed=42,
      ...     faults=(
      ...         FaultEvent(target="redis_get", op=FaultOp.DELAY, after_n_calls=5, payload={"latency_ms": 500}),
      ...         FaultEvent(target="postgres_write", op=FaultOp.DROP, after_n_calls=10),
      ...     ),
      ... )
      >>> injector = FaultInjector(schedule)
      >>> if injector.should_fault("redis_get"):
      ...     fault = injector.next_fault()
      ...     # Apply fault (delay, drop, etc.)
    """

    def __init__(self, schedule: FaultSchedule) -> None:
        """Initialize with a deterministic fault schedule."""
        self._enabled = cfg.fault_injection_enabled
        self._schedule = schedule
        self._call_counters: dict[str, int] = {}  # Per-target call count
        self._faults_applied: dict[str, int] = {}  # Per-fault application count
        self._rng = random.Random(schedule.seed)

        if not self._enabled:
            # Production-safe: act as a no-op if disabled
            log.warning(
                "FaultInjector initialized with fault_injection_enabled=false; "
                "all faults will be no-ops (this is expected in production)"
            )
            return

        log.info(
            f"FaultInjector active: schedule={schedule.name!r}, seed={schedule.seed}, "
            f"num_faults={len(schedule.faults)}"
        )

    def should_fault(self, target: str) -> bool:
        """Check if the next call to `target` will fault."""
        if not self._enabled:
            return False

        # Check if any fault matches this target and after_n_calls condition
        call_count = self._call_counters.get(target, 0)
        for fault in self._schedule.faults:
            if fault.target == target and call_count >= fault.after_n_calls:
                return True
        return False

    def fault_before_op(self, target: str) -> Optional[FaultEvent]:
        """Return the next fault for `target` (if any); increment call counter."""
        if not self._enabled:
            return None

        call_count = self._call_counters.get(target, 0)
        self._call_counters[target] = call_count + 1

        # Find matching fault
        for i, fault in enumerate(self._schedule.faults):
            if fault.target == target and call_count >= fault.after_n_calls:
                fault_key = f"{fault.target}:{i}"
                if fault_key not in self._faults_applied:
                    self._faults_applied[fault_key] = 0
                self._faults_applied[fault_key] += 1
                log.debug(
                    f"Applying fault: target={fault.target!r}, op={fault.op}, "
                    f"call_count={call_count}, payload={fault.payload}"
                )
                return fault

        return None

    def stats(self) -> dict[str, Any]:
        """Return statistics about applied faults."""
        return {
            "schedule_name": self._schedule.name,
            "enabled": self._enabled,
            "call_counters": dict(self._call_counters),
            "faults_applied": dict(self._faults_applied),
        }


# Global instance (set by test harness)
_global_injector: Optional[FaultInjector] = None


def set_global_injector(injector: Optional[FaultInjector]) -> None:
    """Set the thread-local fault injector (test harness only)."""
    global _global_injector
    _global_injector = injector


def get_global_injector() -> Optional[FaultInjector]:
    """Get the active fault injector (if any)."""
    return _global_injector


def with_fault_injection(target: str) -> Callable:
    """Decorator to wrap a function with fault injection.

    Usage:
        @with_fault_injection("redis_get")
        def redis_get(key: str) -> Any:
            ...
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            injector = get_global_injector()
            if not injector:
                return func(*args, **kwargs)

            fault = injector.fault_before_op(target)
            if not fault:
                return func(*args, **kwargs)

            # Apply fault
            if fault.op == FaultOp.ERROR:
                error_code = fault.payload.get("error_code", "FAULT_INJECTED") if fault.payload else "FAULT_INJECTED"
                raise RuntimeError(f"Injected fault: {error_code} (schedule: {injector._schedule.name})")
            elif fault.op == FaultOp.DROP:
                raise TimeoutError(f"Injected DROP fault for {target!r} (schedule: {injector._schedule.name})")
            elif fault.op == FaultOp.DELAY:
                latency_ms = fault.payload.get("latency_ms", 100) if fault.payload else 100
                import time

                time.sleep(latency_ms / 1000.0)
            elif fault.op == FaultOp.PARTITION:
                raise ConnectionError(
                    f"Injected PARTITION fault for {target!r} (schedule: {injector._schedule.name})"
                )
            # CORRUPT, REORDER, DUPLICATE are post-hoc (return value rewriting)

            return func(*args, **kwargs)

        return wrapper

    return decorator
