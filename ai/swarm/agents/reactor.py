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
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from ..sdk.types import Message
from ai.common.config import cfg as _cfg
from .cache import CacheBackend, make_record_key
from .payloads import FreshnessEvent
from .topics import FRESHNESS_EVENTS

_log = logging.getLogger(__name__)


# ── Idempotency ledger ──────────────────────────────────────────


class Ledger(Protocol):
    def already_processed(self, reactor: str, event_id: str) -> bool: ...
    def mark_processed(self, reactor: str, event_id: str) -> None: ...


class InMemoryLedger:
    """Thread-safe ledger. Tests + swarm.demo default.

    Bounded LRU (Pre-Phase-6 audit A1): without a cap, a long-running
    swarm or a backtest replay would accumulate one ``(reactor,
    event_id)`` tuple per event indefinitely. The eviction order is
    insertion order (oldest first); collisions on evicted ids are
    harmless because event_id is content-derived (CONTENT_FRESHNESS
    §15.2) — at worst a stale event re-fires its side effect.
    """

    def __init__(self, max_size: int | None = None) -> None:
        self._lock = threading.Lock()
        if max_size is None:
            max_size = int(_cfg.reactor_ledger_max_size)
        if max_size < 1:
            raise ValueError(f"InMemoryLedger max_size must be >= 1, got {max_size}")
        self._max_size = max_size
        self._seen: "OrderedDict[tuple[str, str], None]" = OrderedDict()

    def already_processed(self, reactor: str, event_id: str) -> bool:
        with self._lock:
            return (reactor, event_id) in self._seen

    def mark_processed(self, reactor: str, event_id: str) -> None:
        with self._lock:
            key = (reactor, event_id)
            if key in self._seen:
                self._seen.move_to_end(key)
                return
            self._seen[key] = None
            while len(self._seen) > self._max_size:
                self._seen.popitem(last=False)


# ── Reactor base ────────────────────────────────────────────────


class ReactorBase:
    """Base class enforcing CONTENT_FRESHNESS §15.2 invariants."""

    name: str = ""
    allowed_planes: tuple[str, ...] = ()
    max_age_sec: int = 24 * 3600  # one day default

    subscribes = (FRESHNESS_EVENTS,)
    publishes: tuple[str, ...] = ()  # subclasses may add — but never FRESHNESS_EVENTS

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
        self._ledger = InMemoryLedger() if ledger is None else ledger

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            ev = FreshnessEvent.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed freshness event: %s", self.name, exc)
            return ()

        if ev.plane not in self.allowed_planes:
            return ()  # plane scope guard

        # Bounded replay window — driven by the payload's emitted_at
        # (which is what reactors care about), with envelope.created_at
        # as a fallback for legacy producers.
        ts_str = ev.emitted_at or msg.envelope.created_at
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if (now - ts).total_seconds() > self.max_age_sec:
                _log.info(
                    "%s: dropping stale event %s (age > %ds)",
                    self.name, ev.event_id, self.max_age_sec,
                )
                return ()
        except ValueError:
            # Third-pass audit (N1): a parse failure means a producer
            # emitted a non-ISO-8601 timestamp — a contract violation.
            # We still proceed (the ledger guard catches replays) but
            # surface the bug at warning level so it doesn't hide.
            _log.warning(
                "%s: unparseable timestamp %r on event %s; "
                "age guard skipped, ledger guard active",
                self.name, ts_str, ev.event_id,
            )

        # Idempotency guard. Key is the deterministic, content-derived
        # event_id from the payload — NOT envelope.message_id, which
        # is fresh per emission and would let upstream retries / a
        # second storage replica trigger this reactor twice
        # (CONTENT_FRESHNESS §15.2).
        #
        # Order: check → react → mark. The classic "inbox" pattern.
        # Side effects in this reactor set are themselves idempotent
        # (`cache.invalidate(k)`, `set.add(record_id)`), so a crash
        # between react() and mark_processed() at worst replays the
        # side effect once — never silently swallows it. By contrast,
        # mark-before-react would *lose* the side effect entirely if
        # react() raised on the first delivery (bus would re-deliver,
        # the ledger guard would short-circuit, and the work would
        # never run).
        if self._ledger.already_processed(self.name, ev.event_id):
            return ()

        result = list(self.react(ev, msg))  # may raise → runner retries
        self._ledger.mark_processed(self.name, ev.event_id)
        return result

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
        ledger: Ledger | None = None,
    ) -> None:
        """The cache key is derived directly from ``ev.source``,
        ``ev.stable_id`` and ``ev.record_type`` (all present on
        every FreshnessEvent), so no store lookup is required —
        the reactor stays loosely coupled from the storage layer.
        """
        super().__init__(ledger=ledger)
        self.cache = cache

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        self.cache.invalidate(
            make_record_key(ev.source, ev.stable_id, ev.record_type)
        )
        return ()


# ── Phase 5 reactors ────────────────────────────────────────────


class TrainerReactor(ReactorBase):
    """Phase 5.4 — debounced retrain trigger.

    Subscribes to ``freshness.events.v1`` and emits ``models.events.v1``
    when (a) the event is a qualifying create/update, (b) accuracy
    against the rolling window stays above ``cfg.drift_accuracy_floor``,
    (c) at least ``cfg.trainer_debounce_sec`` have passed since the
    last retrain for the same ``(predictor_id, league)`` slice.

    The reactor is intentionally decoupled from the actual training
    code path; it emits the *event* so the trainer (or an ops job)
    picks it up. This keeps Phase 5 retrain deterministic + safe to
    run in tests against ``InMemoryBus``.
    """

    name = "reactor.trainer"
    allowed_planes = ("schedule", "live")
    publishes: tuple[str, ...] = ()  # set in __init__ once we import topic

    def __init__(
        self,
        *,
        predictor_ids: Iterable[str],
        ledger: Ledger | None = None,
        debounce_sec: int | None = None,
        accuracy_floor: float | None = None,
        accuracy_lookup: Callable[[str, str | None], float] | None = None,
        clock: Callable[[], float] | None = None,
        version_clock: Callable[[], str] | None = None,
    ) -> None:
        # Defer the topic import to runtime so the module-level
        # imports don't form a cycle (topics.py → predictors → cfg).
        # The cfg import itself is module-level — it has no cycle and
        # paying the import on every TrainerReactor() call wastes a
        # double-digit microseconds per construction (audit §P1).
        from .topics import MODEL_TRAINED  # local import — Phase 5
        self.publishes = (MODEL_TRAINED,)
        self._model_trained_topic = MODEL_TRAINED
        super().__init__(ledger=ledger)
        self._predictor_ids: tuple[str, ...] = tuple(predictor_ids)
        if not self._predictor_ids:
            raise ValueError(
                "reactor.trainer: predictor_ids must list at least one"
            )
        self._debounce_sec = (
            debounce_sec if debounce_sec is not None else _cfg.trainer_debounce_sec
        )
        self._accuracy_floor = (
            accuracy_floor if accuracy_floor is not None else _cfg.drift_accuracy_floor
        )
        self._accuracy_lookup = accuracy_lookup or (lambda _pid, _lid: 1.0)
        self._clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self._version_clock = version_clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self._last_trained: dict[tuple[str, str | None], float] = {}
        self._lock = threading.Lock()

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        # Phase 5.4 qualifying-event filter: only created/updated.
        if ev.change_kind not in ("created", "updated"):
            return ()

        # Avoid the relative-import cycle described in __init__.
        from .payloads import ModelTrained  # local import

        league_id = ev.diff.get("league_id") if isinstance(ev.diff, dict) else None
        out: list[Message] = []
        now = self._clock()
        for predictor_id in self._predictor_ids:
            slice_key = (predictor_id, league_id)
            with self._lock:
                last = self._last_trained.get(slice_key)
                if last is not None and (now - last) < self._debounce_sec:
                    continue
                # Accuracy floor guard — never retrain on a model that
                # is already drifting; surface as proof.flag externally.
                acc = float(self._accuracy_lookup(predictor_id, league_id))
                if acc < self._accuracy_floor:
                    continue
                self._last_trained[slice_key] = now

            payload = ModelTrained(
                predictor_id=predictor_id,
                profile_id=league_id or "default",
                league_id=league_id,
                model_version=self._version_clock(),
                trained_at=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds"),
                metric="accuracy",
                metric_value=acc,
                # `samples` is the trainer's training-set size — the
                # reactor doesn't know it (the trainer fills it in
                # when the actual job runs). Surface the source
                # event_id + record_id via metadata for traceability.
                samples=0,
                metadata={
                    "trigger": "freshness",
                    "event_id": ev.event_id,
                    "record_id": ev.record_id,
                },
            )
            out.append(
                Message.new(
                    self._model_trained_topic,
                    payload.as_dict(),
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                )
            )
        return out


class LivePredictorReactor(ReactorBase):
    """Phase 5.4 — emits ``predict.request`` on live/market changes.

    Maps the freshness event's plane to a market set:

      * ``live`` → 1X2 + AH (score / lineup change)
      * ``market`` → AH + OU2.5 + BTTS (odds tick)

    The reactor writes the request_id itself (``r-<event_id>-<market>``)
    so a re-delivered freshness event yields the same request_ids.
    Combined with the deterministic ``prediction_id`` (consensus side),
    this makes the whole live path idempotent end-to-end.
    """

    name = "reactor.live_predictor"
    allowed_planes = ("live", "market")
    publishes: tuple[str, ...] = ()

    _PLANE_MARKETS: dict[str, tuple[str, ...]] = {
        "live": ("1x2", "ah"),
        "market": ("ah", "ou_2_5", "btts"),
    }

    def __init__(
        self,
        *,
        ledger: Ledger | None = None,
        clock_iso: Callable[[], str] | None = None,
    ) -> None:
        from .topics import PREDICT_REQUEST  # local import to dodge cycle
        self.publishes = (PREDICT_REQUEST,)
        self._predict_request_topic = PREDICT_REQUEST
        super().__init__(ledger=ledger)
        self._clock_iso = clock_iso or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    def react(self, ev: FreshnessEvent, msg: Message) -> Iterable[Message]:
        from .payloads import PredictRequest  # local import to dodge cycle

        markets = self._PLANE_MARKETS.get(ev.plane, ())
        out: list[Message] = []
        league_id = ev.diff.get("league_id") if isinstance(ev.diff, dict) else None
        for market in markets:
            req = PredictRequest(
                request_id=f"r-{ev.event_id}-{market}",
                match_id=ev.stable_id,
                market=market,
                league_id=league_id,
                profile_id=league_id,
                requested_at=self._clock_iso(),
                features={},
                metadata={"trigger": "freshness", "event_id": ev.event_id},
            )
            out.append(
                Message.new(
                    self._predict_request_topic,
                    req.as_dict(),
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                )
            )
        return out


__all__ = [
    "CacheInvalidationReactor",
    "FeatureStoreReactor",
    "InMemoryLedger",
    "Ledger",
    "LivePredictorReactor",
    "ReactorBase",
    "TrainerReactor",
]
