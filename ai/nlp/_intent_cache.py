"""Phase 10 §10.12 — L0 in-process intent cache.

Provides :class:`IntentCache` which:

* Stores (intent, intent_confidence, entity_hash) tuples keyed by
  ``sha256(normalized_text|locale)``.
* Enforces a TTL per entry (configurable; default 300 s).
* LRU-evicts oldest entry when the cache exceeds ``max_entries``.
* **Negative-cache only** for ``meta.unsupported`` intent (§10.12 doctrine:
  never cache ``predict.*`` outputs — those depend on time-varying state).

Doctrine (binding):
* **Monotonic clock for TTL.** ``time.monotonic()`` for expiry checks;
  ``produced_at`` (if needed) uses wall-clock (``time.time()``).
* **Thread-safety.** Single ``threading.Lock`` serializes all operations.
* **Bounded state.** ``max_entries`` cap prevents unbounded growth; LRU
  eviction when full.

Usage::

    cache = IntentCache(max_entries=10000, ttl_s=300)
    
    # Try to get from cache
    result = cache.get(normalized_text="bugün galatasaray maçı", locale="tr-TR")
    if result is not None:
        intent, conf, entity_hash = result
        # ... use cached result
    
    # Put into cache (only for meta.unsupported)
    cache.put(
        normalized_text="...",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.42,
        entity_hash="abc123",
    )
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Optional, Tuple


class IntentCacheEntry:
    """Internal cache entry with TTL tracking.
    
    Attributes:
        intent: The intent label.
        intent_confidence: Calibrated confidence in [0, 1].
        entity_hash: Stable 16-hex-char hash of entity canonical_ids.
        expire_at: Monotonic timestamp when this entry expires.
    """

    __slots__ = ("intent", "intent_confidence", "entity_hash", "expire_at")

    def __init__(
        self,
        intent: str,
        intent_confidence: float,
        entity_hash: str,
        expire_at: float,
    ) -> None:
        self.intent = intent
        self.intent_confidence = intent_confidence
        self.entity_hash = entity_hash
        self.expire_at = expire_at

    def is_expired(self, now: float) -> bool:
        """Return True if this entry has expired."""
        return now >= self.expire_at


class IntentCache:
    """Phase 10 §10.12 L0 in-process intent cache.
    
    Thread-safe LRU cache with TTL. Only caches ``meta.unsupported`` intent
    (negative cache).
    
    Construction parameters:
    
    * ``max_entries`` — LRU cap. Must be >= 1.
    * ``ttl_s`` — TTL per entry in seconds. Must be >= 1.
    * ``clock`` — Monotonic-seconds source; defaults to ``time.monotonic``.
      Tests inject a fake.
    """

    def __init__(
        self,
        *,
        max_entries: int = 10000,
        ttl_s: int = 300,
        clock=time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError(
                f"IntentCache.max_entries must be >= 1; got {max_entries}"
            )
        if ttl_s < 1:
            raise ValueError(
                f"IntentCache.ttl_s must be >= 1; got {ttl_s}"
            )
        self._max_entries = int(max_entries)
        self._ttl_s = float(ttl_s)
        self._clock = clock
        self._lock = threading.Lock()
        # OrderedDict[cache_key] = IntentCacheEntry
        # Insertion-ordered for LRU eviction.
        self._cache: "OrderedDict[str, IntentCacheEntry]" = OrderedDict()

    def _make_key(self, normalized_text: str, locale: str) -> str:
        """Return sha256 hex digest of normalized_text|locale."""
        payload = f"{normalized_text}|{locale}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(
        self,
        normalized_text: str,
        locale: str,
    ) -> Optional[Tuple[str, float, str]]:
        """Retrieve cached intent result if present and not expired.
        
        Returns:
            ``(intent, intent_confidence, entity_hash)`` if cached and fresh,
            else ``None``.
        """
        key = self._make_key(normalized_text, locale)
        now = self._clock()
        
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            
            if entry.is_expired(now):
                # Expired; remove and return miss.
                del self._cache[key]
                return None
            
            # Cache hit; move to end for LRU (refresh access).
            self._cache.move_to_end(key)
            return (entry.intent, entry.intent_confidence, entry.entity_hash)

    def put(
        self,
        normalized_text: str,
        locale: str,
        intent: str,
        intent_confidence: float,
        entity_hash: str,
    ) -> None:
        """Store intent result in cache.
        
        Per §10.12 doctrine, only ``meta.unsupported`` intents are cached
        (never ``predict.*`` outputs). Silently returns without caching if
        the intent is not ``meta.unsupported``.
        
        If the cache is full, evicts the least-recently-used entry (LRU).
        """
        # §10.12 negative-cache discipline: only cache meta.unsupported.
        if intent != "meta.unsupported":
            return
        
        key = self._make_key(normalized_text, locale)
        now = self._clock()
        expire_at = now + self._ttl_s
        
        with self._lock:
            # If key exists, update in place and refresh LRU.
            if key in self._cache:
                self._cache[key] = IntentCacheEntry(
                    intent, intent_confidence, entity_hash, expire_at
                )
                self._cache.move_to_end(key)
                return
            
            # New entry; check if we need to evict.
            if len(self._cache) >= self._max_entries:
                # LRU eviction: remove first (oldest) item.
                self._cache.popitem(last=False)
            
            # Insert new entry.
            self._cache[key] = IntentCacheEntry(
                intent, intent_confidence, entity_hash, expire_at
            )

    def clear(self) -> None:
        """Clear all entries from the cache. Used in tests."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Return the current number of entries in the cache."""
        with self._lock:
            return len(self._cache)
