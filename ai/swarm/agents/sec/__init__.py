"""Phase 7 — Defense agents (sec.input.v1 / sec.scrape.v1 / sec.rate.v1).

Three agents land here per ROADMAP §7. Each runs the **escalation
tier** on top of the Go gateway's deterministic in-process first
line (the §7.7 doctrine: cheap + deterministic stays in Go, the
escalation tier runs as a Python agent on the bus). The split is
what lets the median QA call decide in-process without a Redis hop.

Sub-modules:
* ``_alert``  — generalized debounce helper for ``sec.alert.v1``
                emissions (per-(kind, subject) TTL using monotonic
                clock; ``severity=critical`` bypasses by default).
                Mirrors the Phase 6 ``drift._tripped`` anti-storm
                pattern; one helper class so the three agents do
                not each invent their own.
* ``input``   — `sec.input.v1` escalation-tier classifier wrapper.
                Subscribes ``qa.request``; publishes ``qa.request.v1``
                / ``sec.quarantine.v1`` / ``sec.alert.v1``.
* ``scrape``  — `sec.scrape.v1` upstream-data anomaly detector.
                Subscribes ``scrape.raw``; publishes ``sec.alert.v1``,
                ``sec.quarantine.v1``, and ``proof.flag`` (only for
                post-parse-shape anomalies, per the §7.2 verdict-
                routing contract — Phase 17 patcher channel).
* ``rate``    — `sec.rate.v1` burst detector + denylist writer.
                Subscribes ``sec.alert.v1{kind=rate_throttled}`` and
                ``maint.event.v1{kind=denylist_clear}``; publishes
                ``sec.alert.v1`` and ``sec.denylist.v1``.

Doctrine recap (binding for every agent in this package):

* **Fail open, alarm loud.** No defense agent ever blocks the happy
  path. Failure modes (classifier OOM, Redis partition, batch
  deadline missed) resolve to the permissive verdict and emit a
  ``sec.alert.v1`` so operators see the degradation. The
  defense-in-depth contract (ROADMAP §7) is what makes this safe:
  Phase 10 NLP answers from templates, Phase 4 processor never
  executes upstream JS, the Phase 9 gateway carries a per-process
  secondary token bucket. If a future phase removes any of those,
  the corresponding fail-open default must be reconsidered.

* **Idempotent under at-least-once redelivery.** Every handler key-
  dedups inside its bounded LRU before mutating state.

* **Bounded state.** Every in-process map is ``cfg``-capped with
  insertion-order LRU eviction; overflow emits a ``sec.alert.v1``
  outside the lock.

* **Monotonic clocks for in-process windows.** Pre-Phase-7 audit
  M2/M4 — ``time.monotonic()`` for window math; only the on-the-
  wire ``produced_at`` and Redis TTLs stay wall-clock.

* **No `proof.flag` from sec.input.v1 / sec.rate.v1.** The two
  taxonomies are disjoint (Phase 6 doctrine + §7 cross-phase
  alignment). Only ``sec.scrape.v1`` may bridge to ``proof.flag``,
  and only for post-parse-shape anomalies that route to the
  Phase 17 patcher.
"""
from __future__ import annotations

from .input import SecInputAgent
from .rate import SecRateAgent
from .scrape import SecScrapeAgent
from ._allowlist import (
    AllowlistCache,
    InMemoryAllowlistReader,
    PatternAllowlistReader,
    compute_pattern_key,
)

__all__ = [
    "SecInputAgent",
    "SecRateAgent",
    "SecScrapeAgent",
    "AllowlistCache",
    "InMemoryAllowlistReader",
    "PatternAllowlistReader",
    "compute_pattern_key",
]
