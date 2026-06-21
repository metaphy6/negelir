"""Phase 7 §7.5 — bounded request-id dedup helper.

The §7.5 binding states:

    > "Exactly one publisher per ``request_id``" is a producer-side
    > promise; under Redis Streams at-least-once semantics, gateway
    > crashes between publish and ack can replay. The NLP layer
    > (Phase 10) MUST dedup by ``request_id`` over a sliding window
    > of ``cfg.qa_request_v1_dedup_window_s`` (default 300, comfortably
    > larger than the SDK retry budget * max attempts).

This module ships the deduper so the Phase 10 NLP layer (and the
boundary tests today) consume one canonical implementation. It is
intentionally tiny — an ``OrderedDict`` keyed on ``request_id`` with
insertion-order LRU eviction and a monotonic-clock TTL.

Doctrine:

* **Bounded state.** The shard size cap (``max_keys``) is the only
  thing standing between the deduper and unbounded growth under a
  request-id-spray attack — the rate limiter (§7.3) bounds the
  inbound request rate, but a misbehaving producer could still
  exhaust the deduper. The cap is a config knob, not a hard-coded
  constant, so operators can tune for their request shape.
* **Monotonic clock.** Wall-clock TTLs go negative under NTP slew
  (per pre-Phase-7 audit M2/M4 — the same fix the consensus and
  drift agents already adopted). Tests inject a fake clock.
* **No bus dependency.** This is a pure data structure; it does
  not import from ``swarm.sdk.bus`` so the NLP layer can use it
  without wiring a runner.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable


class RequestIdDeduper:
    """Sliding-window deduper for ``qa.request.v1.request_id``.

    Usage::

        deduper = RequestIdDeduper(window_s=300, max_keys=10_000)
        if deduper.seen("req-abc"):
            return  # already processed
        process(...)

    ``seen()`` returns ``True`` iff the key was already observed
    within the window AND has not been evicted by the LRU cap. The
    *first* call for a given key always returns ``False`` and
    records the hit; subsequent calls within ``window_s`` return
    ``True``.
    """

    __slots__ = ("_window_s", "_max_keys", "_clock", "_lock", "_seen")

    def __init__(
        self,
        *,
        window_s: float,
        max_keys: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        self._window_s = float(window_s)
        self._max_keys = int(max_keys)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        # OrderedDict[request_id] -> monotonic timestamp recorded.
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def seen(self, request_id: str) -> bool:
        """Return whether ``request_id`` was already processed.

        Always records the (request_id, now) pair on a miss — the
        method is the single ingestion point so callers cannot
        forget to register the key after deciding to process.
        """
        if not request_id:
            # Empty / None defensively treated as never-seen so a
            # malformed envelope cannot pin a single dedup slot for
            # the lifetime of the process. The boundary test in
            # `test_phase7_completion.py` covers this branch.
            return False
        now = self._clock()
        cutoff = now - self._window_s
        with self._lock:
            # Age out expired entries from the head (insertion-order
            # is monotonic in time, so the head is always the oldest).
            while self._seen:
                k, ts = next(iter(self._seen.items()))
                if ts >= cutoff:
                    break
                self._seen.popitem(last=False)
            existing = self._seen.get(request_id)
            if existing is not None and existing >= cutoff:
                return True
            # Either never seen or aged out — record fresh.
            self._seen[request_id] = now
            self._seen.move_to_end(request_id)
            # LRU cap (defense-in-depth on top of the time window).
            while len(self._seen) > self._max_keys:
                self._seen.popitem(last=False)
            return False

    def size(self) -> int:
        """Current number of tracked request-ids (post age-out)."""
        with self._lock:
            return len(self._seen)


__all__ = ["RequestIdDeduper"]
