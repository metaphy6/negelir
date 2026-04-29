"""Phase 4.5 + Phase 6 — Cache agent.

Subscribes:
  * ``match.stored`` (Phase 4.5) — caches normalized record keys with
    ``cfg.cache_record_ttl_sec``.
  * ``predict.approved.v1`` (Phase 6, Wave A.1) — caches
    proofreader-approved predictions with
    ``cfg.cache_prediction_ttl_sec``.

The cache **must not** subscribe to ``predict.final`` directly:
that topic carries CANDIDATE consensus output that has not yet
passed proofreader quorum (ROADMAP §736). The boundary test in
``test_boundary_discipline.py`` enforces this rule.

The Redis-backed implementation lives at ``RedisCacheBackend``; tests
use the ``InMemoryCacheBackend``.

Key shapes are intentionally flat:

    record:<source>:<source_match_id>:<record_type>
    prediction:<match_id>:<market>:<prediction_id>

so the API can do a single GET. TTLs are config-driven via
``cfg.cache_record_ttl_sec`` and ``cfg.cache_prediction_ttl_sec``.

A ``Cache.invalidate(key)`` hook is exposed so the future gRPC
``Invalidate(key)`` server (Phase 9 API surface) can call directly
without going through the bus.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Iterable, Protocol

from common.config import cfg

from ..sdk.types import Message
from .payloads import MatchStored, PredictApproved
from .topics import MATCH_STORED, PREDICT_APPROVED

_log = logging.getLogger(__name__)


class CacheBackend(Protocol):
    def set(self, key: str, value: str, *, ttl_sec: int) -> None: ...
    def get(self, key: str) -> str | None: ...
    def invalidate(self, key: str) -> None: ...


class InMemoryCacheBackend:
    """Thread-safe in-memory backend for tests + swarm.demo."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, tuple[str, float]] = {}
        self._clock = clock

    def set(self, key: str, value: str, *, ttl_sec: int) -> None:
        with self._lock:
            self._data[key] = (value, self._clock() + ttl_sec)

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, exp = entry
            if exp < self._clock():
                self._data.pop(key, None)
                return None
            return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def __len__(self) -> int:  # convenience for tests
        with self._lock:
            return len(self._data)


def make_record_key(source: str, key_id: str, record_type: str) -> str:
    """Build the canonical cache key for a normalized record.

    ``key_id`` is the deterministic identifier the API uses to look
    the record up — today the storage agent passes ``stable_id``
    (sha1 of source + source_match_id, truncated). The parameter is
    deliberately *not* called ``source_match_id`` to make the contract
    explicit: callers may pass any stable, deterministic id, but it
    must agree with what the API resolver expects.
    """
    return f"record:{source}:{key_id}:{record_type}"


def make_prediction_key(match_id: str, market: str, prediction_id: str) -> str:
    """Build the canonical cache key for a proofreader-approved prediction.

    Phase 6 (Wave A.1): the cache subscribes to ``predict.approved.v1``
    only. ``prediction_id`` is the deterministic id stamped by
    consensus (sha256 of ``match_id|market|request_id|calibration_version``)
    — making the key unique per request lets the API serve a stable
    response even when the same ``(match_id, market)`` is re-predicted.
    """
    return f"prediction:{match_id}:{market}:{prediction_id}"


class CacheAgent:
    name = "cache.v1"
    subscribes: tuple[str, ...] = (MATCH_STORED, PREDICT_APPROVED)
    publishes: tuple[str, ...] = ()  # cache writes are side-effects, not bus events

    def __init__(self, backend: CacheBackend | None = None) -> None:
        # Explicit None check — backends with __len__ (the in-memory one)
        # are falsy when empty, so `backend or default()` would silently
        # discard a freshly-constructed user-supplied backend.
        self.backend = InMemoryCacheBackend() if backend is None else backend

    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == MATCH_STORED:
            return self._handle_stored(msg)
        if topic == PREDICT_APPROVED:
            return self._handle_approved(msg)
        # The bus dispatcher should never deliver an unsubscribed topic;
        # log loudly and ignore (don't raise — a single bad message must
        # not kill the agent loop).
        _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
        return ()

    def _handle_stored(self, msg: Message) -> Iterable[Message]:
        try:
            stored = MatchStored.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed match.stored: %s", self.name, exc)
            return ()

        if stored.change_kind == "unchanged":
            return ()  # nothing to invalidate, nothing to refresh

        key = make_record_key(stored.source, stored.stable_id, stored.record_type)
        # We store a small marker; the API resolves the row by id.
        # Bigger payloads belong in the gRPC cache server, not in-bus.
        # Read directly from cfg — no `getattr` fallback. The triangle
        # (config.py + defaults.yaml + .env.example) guarantees the
        # field exists; a fallback literal here would silently mask
        # field-rename drift instead of failing loudly.
        ttl = int(cfg.cache_record_ttl_sec)
        self.backend.set(
            key,
            f"id={stored.record_id}",
            ttl_sec=ttl,
        )
        return ()

    def _handle_approved(self, msg: Message) -> Iterable[Message]:
        try:
            approved = PredictApproved.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.approved.v1: %s", self.name, exc)
            return ()

        key = make_prediction_key(
            approved.match_id, approved.market, approved.prediction_id
        )
        # Store the full predict.final payload (already carried verbatim
        # under `final` in the approval envelope) so the API can serve it
        # without a join. JSON-encoded so the in-memory + Redis backends
        # share the same value contract.
        ttl = int(cfg.cache_prediction_ttl_sec)
        self.backend.set(
            key,
            json.dumps(approved.final, separators=(",", ":"), sort_keys=True),
            ttl_sec=ttl,
        )
        return ()


__all__ = [
    "CacheAgent",
    "CacheBackend",
    "InMemoryCacheBackend",
    "make_prediction_key",
    "make_record_key",
]
