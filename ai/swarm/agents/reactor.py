"""Phase 4.7 — Freshness-event reactors.

Reactors subscribe to `freshness.events.v1`, perform plane-bounded
side effects, and **never** emit back to the freshness topic. The
`ReactorBase` enforces the CONTENT_FRESHNESS.md §15.2 invariants:

  * **Idempotency.** Each reactor maintains its own
    ``processed_events`` ledger keyed by ``event_id``. The base class
    short-circuits a second observation of the same event.
  * **Plane scope.** Subclasses declare ``allowed_planes``; events
    outside that scope are dropped without side effects.
  * **No back-emission.** ``publishes`` may not include
    ``freshness.events.v1`` (asserted at construction).
  * **Bounded replay.** ``max_age_sec`` (per reactor) caps how stale
    an event can be before it is dropped.

The default ledger is in-process (``InMemoryLedger``); production
reactors swap in ``PostgresLedger`` backed by the
``reactor_processed_events`` migration table.

Two first-cut reactors ship in this phase:

  * ``FeatureStoreReactor`` — bumps a per-stable_id "needs recompute"
    counter so the trainer/live-predictor can prioritize.
  * ``CacheInvalidationReactor`` — calls ``cache.invalidate(key)``.

Trainer / live-predictor / NLP / market reactors are stubbed with
``NotImplementedError`` so the wiring exists but the deeper work
deferred to its own phase keeps a clear signal.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Iterable, Protocol

from ..sdk.types import Message
from .cache import CacheBackend, make_record_key
from .payloads import FreshnessEvent
from .topics import FRESHNESS_EVENTS

_log = logging.getLogger(__name__)


# ── Idempotency ledger ──────────────────────────────────────────


class Ledger(Protocol):
    def already_processed(self, reactor: str, event_id: str) -> bool: ...
    def mark_processed(self, reactor: str, event_id: str) -> None: ...


class InMemoryLedger:
    """Thread-safe ledger. Tests + swarm-demo default."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[tuple[str, str]] = set()

    def already_processed(self, reactor: str, event_id: str) -> bool:
        with self._lock:
            return (reactor, event_id) in self._seen

    def mark_processed(self, reactor: str, event_id: str) -> None:
        with self._lock:
            self._seen.add((reactor, event_id))


# ── Reactor base ────────────────────────────────────────────────


class ReactorBase:
    """Base class enforcing CONTENT_FRESHNESS §15.2 invariants."""

    name: str = ""
    allowed_planes: tuple[str, ...] = ()
    max_age_sec: int = 24 * 3600  # one day default

    subscribes = [FRESHNESS_EVENTS]
    publishes: list = []  # subclasses may add — but never FRESHNESS_EVENTS

    def __init__(self, ledger: Ledger | None = None) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__}: name is required")
        if FRESHNESS_EVENTS in self.publishes:
            raise ValueError(
                f"{self.name}: reactors must not publish to "
                f"{FRESHNESS_EVENTS} (back-emission ban)"
            )
        if not self.allowed_planes:
            raise ValueError(
                f"{self.name}: allowed_planes must list at least one plane"
            )
        self._ledger = ledger or InMemoryLedger()

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            ev = FreshnessEvent.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed freshness event: %s", self.name, exc)
            return ()

        if ev.plane not in self.allowed_planes:
            return ()  # plane scope guard

        # Bounded replay window.
        try:
            ts = datetime.fromisoformat(msg.envelope.created_at)
            now = datetime.now(ts.tzinfo or timezone.utc)
            if (now - ts).total_seconds() > self.max_age_sec:
                _log.info(
                    "%s: dropping stale event %s (age > %ds)",
                    self.name, msg.envelope.message_id, self.max_age_sec,
                )
                return ()
        except ValueError:
            pass  # age unknown — let the ledger guard repeats

        # Idempotency guard.
        event_id = msg.envelope.message_id
        if self._ledger.already_processed(self.name, event_id):
            return ()
        # Mark *before* side effect so a crash mid-effect cannot
        # trigger a second run. Recovery semantics:
        # at-least-once delivery + at-most-once side effect.
        self._ledger.mark_processed(self.name, event_id)

        try:
            return list(self.react(ev, msg))
        except Exception:
            # Re-raise so the runner counts the retry; the ledger
            # entry stays so the same event_id will not re-trigger.
            # Operators replay via `make reactor.replay REACTOR=... SINCE=...`.
            raise

    # ── Subclass override ───────────────────────────────────────────
    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        raise NotImplementedError


# ── Concrete reactors ───────────────────────────────────────────


class FeatureStoreReactor(ReactorBase):
    """Marks a record id as needing feature recomputation.

    Fed downstream by the Phase 5 trainer / Phase 6 live-predictor,
    which read this set to prioritize work. Today it is an in-process
    set; the Phase 5 stack swaps in Redis.
    """

    name = "reactor.feature_store"
    allowed_planes = ("schedule", "live")

    def __init__(self, ledger: Ledger | None = None) -> None:
        super().__init__(ledger=ledger)
        self.dirty_record_ids: set[int] = set()
        self._lock = threading.Lock()

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        with self._lock:
            self.dirty_record_ids.add(ev.record_id)
        return ()


class CacheInvalidationReactor(ReactorBase):
    """Drops cache entries when their backing record changes."""

    name = "reactor.cache_invalidate"
    allowed_planes = ("schedule", "live", "market", "editorial", "reference")

    def __init__(
        self,
        cache: CacheBackend,
        *,
        store_lookup: callable | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        """``store_lookup(record_id) -> (source, source_match_id, record_type) | None``

        Required so we can build the cache key from the record id.
        Tests pass a closure over the in-memory store; production
        wires a tiny SQL select.
        """
        super().__init__(ledger=ledger)
        self.cache = cache
        self._store_lookup = store_lookup

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        if self._store_lookup is None:
            return ()
        located = self._store_lookup(ev.record_id)
        if located is None:
            return ()
        source, source_match_id, record_type = located
        self.cache.invalidate(make_record_key(source, source_match_id, record_type))
        return ()


# ── Stubs for later phases ──────────────────────────────────────


class TrainerReactor(ReactorBase):  # pragma: no cover - Phase 5 placeholder
    name = "reactor.trainer"
    allowed_planes = ("schedule", "live")

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        raise NotImplementedError("Trainer reactor wires up in Phase 5")


class LivePredictorReactor(ReactorBase):  # pragma: no cover - Phase 6 placeholder
    name = "reactor.live_predictor"
    allowed_planes = ("live", "market")

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        raise NotImplementedError("Live-predictor reactor wires up in Phase 6")


__all__ = [
    "CacheInvalidationReactor",
    "FeatureStoreReactor",
    "InMemoryLedger",
    "Ledger",
    "LivePredictorReactor",
    "ReactorBase",
    "TrainerReactor",
]
