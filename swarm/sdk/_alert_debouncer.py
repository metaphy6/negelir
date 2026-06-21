"""Phase 10 §10.11 — Shared ``_BaseAlertDebouncer`` extracted from Phase 7's ``SecAlertDebouncer``.

This base class provides the (kind, subject) debounce with bounded LRU that both
``SecAlertDebouncer`` (Phase 7 §7.4) and ``AlertDebouncer`` (Phase 10 NLP alerts)
reuse. The extraction preserves backward compatibility: ``SecAlertDebouncer`` is now
a thin subclass with the same public API.

Doctrine (binding):
* **Monotonic clock.** TTLs use ``time.monotonic()`` for in-process math; only the
  on-the-wire ``produced_at`` field stays wall-clock.
* **Bounded state.** ``max_buckets`` caps the number of (kind, subject) pairs we track;
  insertion-order LRU evicts the oldest. Eviction does NOT signal correctness — the
  evicted pair just loses its suppression context, so the *next* fire emits as if it
  were the first occurrence (worst case: one extra alert on bucket evict). Overflow
  does not itself emit an alert (would recurse).
* **Thread-safety.** A single ``threading.Lock`` serializes the bookkeeping. Holds
  nanoseconds per call; the agents never call in tight loops (one alert per inbound
  event at most).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class DebounceDecision:
    """Result of a debounce check.

    * ``emit=True``  → caller should publish the alert. ``reason``
      is the (possibly augmented) reason string to put on the wire.
    * ``emit=False`` → caller suppresses the alert; ``reason`` is
      ignored. ``suppressed_count`` is the running tally.
    """

    emit: bool
    reason: str
    suppressed_count: int


class _BaseAlertDebouncer:
    """Per-(kind, subject) debounce with a bounded LRU.

    Agents instantiate ONE debouncer per process and call :meth:`decide` before every
    alert emission. The helper does not own the alert publication — the caller does —
    so the helper has zero coupling to the bus.

    Construction parameters:

    * ``ttl_s``  — TTL per (kind, subject) bucket.
    * ``critical_bypass`` — when ``True`` (the default), severity=``critical`` skips
      the gate entirely.
    * ``max_buckets`` — LRU cap. Below 1 raises ``ValueError`` at construction.
    * ``clock`` — monotonic-seconds source; defaults to ``time.monotonic``. Tests
      inject a fake.
    """

    def __init__(
        self,
        *,
        ttl_s: int,
        critical_bypass: bool = True,
        max_buckets: int = 100_000,
        clock=time.monotonic,
    ) -> None:
        if max_buckets < 1:
            raise ValueError(
                f"_BaseAlertDebouncer.max_buckets must be >= 1; got {max_buckets}"
            )
        if ttl_s < 0:
            raise ValueError(
                f"_BaseAlertDebouncer.ttl_s must be >= 0; got {ttl_s}"
            )
        self._ttl_s = float(ttl_s)
        self._critical_bypass = bool(critical_bypass)
        self._max_buckets = int(max_buckets)
        self._clock = clock
        self._lock = threading.Lock()
        # OrderedDict[(kind, subject)] = (last_emit_monotonic_s, suppressed_count)
        self._buckets: "OrderedDict[Tuple[str, str], Tuple[float, int]]" = OrderedDict()

    def decide(
        self,
        kind: str,
        subject: str | None,
        severity: str,
        reason: str,
    ) -> DebounceDecision:
        """Return whether to emit the alert.

        ``subject=None`` collapses to the empty string so a
        kind-only alert (e.g. ``pattern_reload``) still gets a
        deterministic bucket.
        """
        # Critical bypass — fast path, no lock needed.
        if severity == "critical" and self._critical_bypass:
            return DebounceDecision(emit=True, reason=reason, suppressed_count=0)

        # ttl_s == 0 disables debouncing entirely (operator escape hatch
        # for noisy-environment debugging; never set in prod).
        if self._ttl_s == 0:
            return DebounceDecision(emit=True, reason=reason, suppressed_count=0)

        key = (str(kind), str(subject or ""))
        now = self._clock()
        with self._lock:
            existing = self._buckets.get(key)
            if existing is None:
                # First occurrence — emit, install a fresh bucket.
                self._buckets[key] = (now, 0)
                self._evict_overflow_locked()
                return DebounceDecision(emit=True, reason=reason, suppressed_count=0)
            last_emit, suppressed = existing
            elapsed = now - last_emit
            if elapsed >= self._ttl_s:
                # TTL expired — emit, augment reason with the suppress count.
                augmented = (
                    f"{reason} (suppressed: {suppressed})"
                    if suppressed > 0
                    else reason
                )
                self._buckets[key] = (now, 0)
                # Touch LRU position.
                self._buckets.move_to_end(key)
                return DebounceDecision(
                    emit=True, reason=augmented, suppressed_count=suppressed
                )
            # Within TTL — suppress.
            self._buckets[key] = (last_emit, suppressed + 1)
            self._buckets.move_to_end(key)
            return DebounceDecision(
                emit=False, reason=reason, suppressed_count=suppressed + 1
            )

    def reset(self) -> None:
        """Drop all suppression state. Tests use this between cases."""
        with self._lock:
            self._buckets.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)

    # ── Internals ─────────────────────────────────────────────────
    def _evict_overflow_locked(self) -> None:
        """Caller holds ``self._lock``. Drop the oldest entries until
        we are within ``self._max_buckets``. Insertion-order LRU."""
        while len(self._buckets) > self._max_buckets:
            self._buckets.popitem(last=False)


__all__ = ["DebounceDecision", "_BaseAlertDebouncer"]
