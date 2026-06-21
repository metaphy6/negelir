"""Phase 10 §10.12 — Singleflight collapse for concurrent identical queries.

Mirrors `golang.org/x/sync/singleflight` using Python threading.Event.
When multiple concurrent requests arrive with the same stable key, only
the first performs the work; others wait on the Event and share the result.

This is a **per-pod** optimization (no Redis coordination — the cost
outweighs the benefit at v1 scale per §10.21.4).

Phase 10 §10.21.2 adds a background sweeper that periodically drops orphaned
events (from crashed dispatchers) and enforces a hard cap on inflight count.

Typical usage::

    sf = Singleflight[str]()

    def do_work(key: str) -> str:
        # Expensive operation
        return f"result-{key}"

    # Many concurrent calls with the same key collapse to one do_work()
    result = sf.do(key="abc", fn=lambda: do_work("abc"))

With sweeper (NLP dispatcher pattern)::

    def on_swept(count: int) -> None:
        # emit nlp.event.v1{kind=singleflight_event_swept, count=...}
        pass

    def on_overflow(current_count: int) -> None:
        # emit nlp.alert.v1{kind=nlp_singleflight_overflow, severity=warn}
        pass

    sf = Singleflight[str](
        sweep_interval_s=30,
        event_max_age_s=60,
        max_inflight=2048,
        on_swept=on_swept,
        on_overflow=on_overflow,
    )
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

_log = logging.getLogger(__name__)


@dataclass
class _Flight(Generic[T]):
    """Tracks an inflight request: waiters share this event and result.
    
    §10.21.2: created_at timestamp enables orphan detection by the sweeper.
    """

    event: threading.Event
    created_at: float = field(default_factory=time.monotonic)
    result: T | None = None
    error: Exception | None = None


class Singleflight(Generic[T]):
    """Collapses concurrent identical requests to a single execution.

    Thread-safe. The first caller for a given key executes ``fn``; subsequent
    callers with the same key wait on a threading.Event until the first
    completes, then all receive the same result (or exception).

    After the work completes, the key is removed from the inflight map so
    future requests execute fresh (this is NOT a cache — TTL discipline lives
    in the cache layer).
    
    §10.21.2 sweeper: optionally start a background thread that drops orphaned
    events older than ``event_max_age_s`` and enforces ``max_inflight`` cap.
    Sweeper runs every ``sweep_interval_s`` and invokes the ``on_swept`` and
    ``on_overflow`` callbacks (caller emits nlp.event.v1 / nlp.alert.v1).
    """

    def __init__(
        self,
        *,
        sweep_interval_s: int | None = None,
        event_max_age_s: int | None = None,
        max_inflight: int | None = None,
        on_swept: Callable[[int], None] | None = None,
        on_overflow: Callable[[int], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize Singleflight, optionally with sweeper.
        
        Args:
            sweep_interval_s: If set, start a background sweeper that runs
                every this many seconds. Requires event_max_age_s.
            event_max_age_s: Orphan threshold (seconds). Events older than
                this are dropped by the sweeper.
            max_inflight: Hard cap on inflight event count. Over-cap triggers
                on_overflow callback and rejects new do() calls.
            on_swept: Callback(count) invoked when sweeper drops events.
            on_overflow: Callback(current_count) invoked when inflight > max.
            clock: Monotonic time source (tests inject a fake).
        """
        self._lock = threading.Lock()
        self._inflight: dict[str, _Flight[T]] = {}
        self._clock = clock
        self._max_inflight = max_inflight
        self._on_overflow = on_overflow
        
        # Sweeper thread (§10.21.2)
        self._sweeper_thread: threading.Thread | None = None
        self._stop_sweeper = threading.Event()
        if sweep_interval_s is not None:
            if event_max_age_s is None:
                raise ValueError(
                    "Singleflight: sweep_interval_s requires event_max_age_s"
                )
            self._sweep_interval_s = float(sweep_interval_s)
            self._event_max_age_s = float(event_max_age_s)
            self._on_swept = on_swept
            self._sweeper_thread = threading.Thread(
                target=self._sweeper_loop, daemon=True, name="singleflight-sweeper"
            )
            self._sweeper_thread.start()
            _log.debug(
                "Singleflight sweeper started: interval=%ds, max_age=%ds",
                sweep_interval_s,
                event_max_age_s,
            )

    def do(self, key: str, fn: Callable[[], T]) -> T:
        """Execute fn() or wait for an inflight execution with the same key.

        Args:
            key: Stable identifier for the work (e.g., sha256 of request params).
            fn: Callable that produces the result. Only invoked by the first
                caller for a given key; subsequent callers share the result.

        Returns:
            The result from fn(), or the shared result from an inflight call.

        Raises:
            RuntimeError: When max_inflight cap is exceeded (§10.21.2).
            Any exception raised by fn() is re-raised to all waiters.
        """
        # Check if work is already inflight
        with self._lock:
            # §10.21.2: enforce max_inflight cap
            if (
                self._max_inflight is not None
                and len(self._inflight) >= self._max_inflight
            ):
                current = len(self._inflight)
                # Callback outside lock (may emit alert)
                if self._on_overflow is not None:
                    self._on_overflow(current)
                raise RuntimeError(
                    f"Singleflight overflow: {current} >= {self._max_inflight}"
                )
            
            flight = self._inflight.get(key)
            if flight is not None:
                # Someone else is already doing the work; wait for them
                # Keep a reference to the flight so we can read result/error later
                is_doer = False
            else:
                # We're the first; create the flight and do the work
                flight = _Flight[T](event=threading.Event())
                self._inflight[key] = flight
                is_doer = True

        if not is_doer:
            # We're a waiter; block until the doer completes
            flight.event.wait()
            # Work is done; retrieve result from our flight reference
            # (flight may have been popped from _inflight already)
            if flight.error is not None:
                raise flight.error
            return flight.result  # type: ignore[return-value]
        else:
            # We're the doer; execute fn()
            try:
                result = fn()
                flight.result = result
                flight.error = None
                return result
            except Exception as err:
                flight.result = None
                flight.error = err
                raise
            finally:
                # Remove from inflight map, then wake all waiters
                with self._lock:
                    self._inflight.pop(key, None)
                # Set event outside lock to avoid holding lock during wakeup
                flight.event.set()

    def inflight_count(self) -> int:
        """Return the count of currently inflight keys (for observability)."""
        with self._lock:
            return len(self._inflight)
    
    def stop(self) -> None:
        """Stop the sweeper thread (if running). Idempotent."""
        if self._sweeper_thread is not None:
            self._stop_sweeper.set()
            self._sweeper_thread.join(timeout=5.0)
            self._sweeper_thread = None
    
    def _sweeper_loop(self) -> None:
        """Background thread: drop orphaned events every sweep_interval_s."""
        while not self._stop_sweeper.wait(timeout=self._sweep_interval_s):
            swept_count = self._sweep_once()
            if swept_count > 0:
                _log.debug("Singleflight sweeper dropped %d orphaned events", swept_count)
                if self._on_swept is not None:
                    try:
                        self._on_swept(swept_count)
                    except Exception as exc:
                        _log.warning("Singleflight on_swept callback failed: %s", exc)
    
    def _sweep_once(self) -> int:
        """Sweep orphaned events older than event_max_age_s. Returns count dropped."""
        now = self._clock()
        dropped_keys: list[str] = []
        with self._lock:
            for key, flight in list(self._inflight.items()):
                age = now - flight.created_at
                if age >= self._event_max_age_s:
                    dropped_keys.append(key)
                    self._inflight.pop(key, None)
                    # Wake any waiters with an error so they don't hang forever
                    flight.error = RuntimeError(
                        f"Singleflight event orphaned (age={age:.1f}s)"
                    )
                    flight.event.set()
        return len(dropped_keys)
