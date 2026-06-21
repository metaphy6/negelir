"""Phase 7 §7.4 — Generalized ``sec.alert.v1`` debounce helper.

Without this, a burst attack produces an alert storm that drowns
operator dashboards (the same anti-pattern Phase 6 ``drift.v1.
_tripped`` already solved for retrain events). Each (kind, subject)
pair has a TTL of ``cfg.sec_alert_debounce_ttl_s`` (default 60 s).
During the TTL, repeated triggers increment an in-process
``suppressed_count``; the next emission after TTL expiry carries
``reason = "<original> (suppressed: <N>)"``.

Severity-``critical`` kinds bypass debounce by default (operator-
paging events should always page); knob
``cfg.sec_alert_critical_debounce_enabled`` (default ``False``)
flips this for noisy environments.

Implementation notes (binding):
* **Monotonic clock.** Pre-Phase-7 audit M2/M4 — TTLs use
  ``time.monotonic()`` for in-process math; only the on-the-wire
  ``produced_at`` field stays wall-clock.
* **Bounded state.** ``cfg.sec_alert_debouncer_max_buckets`` (F7.2)
  caps the number of (kind, subject) pairs we track; insertion-order
  LRU evicts the oldest. Eviction does NOT signal correctness — the
  evicted pair just loses its suppression context, so the *next*
  fire emits as if it were the first occurrence (worst case: one
  extra alert on bucket evict). Overflow does not itself emit an
  alert (would recurse into this same helper).
* **Thread-safety.** A single ``threading.Lock`` serializes the
  bookkeeping. Holds nanoseconds per call; the agents never call
  in tight loops (one alert per inbound event at most).

**Phase 10 §10.11 refactor:** The debounce logic is now in
``swarm.sdk._BaseAlertDebouncer``; ``SecAlertDebouncer`` is a thin
subclass that preserves the Phase 7 API.
"""
from __future__ import annotations

from swarm.sdk._alert_debouncer import DebounceDecision, _BaseAlertDebouncer


class SecAlertDebouncer(_BaseAlertDebouncer):
    """Per-(kind, subject) debounce with a bounded LRU.

    The agents instantiate ONE debouncer per process and call
    :meth:`decide` before every ``SecAlert(...)`` emission. The
    helper does not own the alert publication — the caller does
    — so the helper has zero coupling to the bus.

    Construction parameters:

    * ``ttl_s``  — TTL per (kind, subject) bucket. Use
      ``cfg.sec_alert_debounce_ttl_s``.
    * ``critical_bypass`` — when ``True`` (the default), severity=
      ``critical`` skips the gate entirely. Mirror the negation of
      ``cfg.sec_alert_critical_debounce_enabled`` (``False`` →
      bypass; ``True`` → debounce critical too).
    * ``max_buckets`` — LRU cap. Use
      ``cfg.sec_alert_debouncer_max_buckets`` (F7.2 — a dedicated
      knob, distinct from the rate agent's per-subject bound, so
      operators can tune the rate-agent's anti-spray cap during
      incident response without simultaneously truncating the
      debouncer in unrelated agents). Below 1 raises ``ValueError``
      at construction.
    * ``clock`` — monotonic-seconds source; defaults to
      ``time.monotonic``. Tests inject a fake.
    """

    pass  # All logic is now in _BaseAlertDebouncer


__all__ = ["DebounceDecision", "SecAlertDebouncer"]
