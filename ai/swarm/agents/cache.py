"""Phase 4.5 — Cache agent.

Subscribes `match.stored` (and later `predict.final`) and updates a
key/value cache that the API serves from. The Redis-backed
implementation lives at `RedisCacheBackend`; tests use the
``InMemoryCacheBackend``.

The cache key shape is intentionally flat:

    record:<source>:<source_match_id>:<record_type>

so the API can do a single GET. TTLs are config-driven via
``cfg.cache_record_ttl_sec``.

A ``Cache.invalidate(key)`` hook is exposed so the future gRPC
``Invalidate(key)`` server (Phase 9 API surface) can call directly
without going through the bus.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Iterable, Protocol

from common.config import cfg

from ..sdk.types import Message
from .payloads import MatchStored
from .topics import MATCH_STORED

_log = logging.getLogger(__name__)


class CacheBackend(Protocol):
    def set(self, key: str, value: str, *, ttl_sec: int) -> None: ...
    def get(self, key: str) -> str | None: ...
    def invalidate(self, key: str) -> None: ...


class InMemoryCacheBackend:
    """Thread-safe in-memory backend for tests + swarm-demo."""

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


class CacheAgent:
    name = "cache.v1"
    subscribes: tuple[str, ...] = (MATCH_STORED,)
    publishes: tuple[str, ...] = ()  # cache writes are side-effects, not bus events

    def __init__(self, backend: CacheBackend | None = None) -> None:
        # Explicit None check — backends with __len__ (the in-memory one)
        # are falsy when empty, so `backend or default()` would silently
        # discard a freshly-constructed user-supplied backend.
        self.backend = InMemoryCacheBackend() if backend is None else backend

    def handle(self, msg: Message) -> Iterable[Message]:
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


__all__ = [
    "CacheAgent",
    "CacheBackend",
    "InMemoryCacheBackend",
    "make_record_key",
]
