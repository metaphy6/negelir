"""Phase 8.16.4 — cardinality-safe ``maint.ack.v1`` metric helper.

Doctrine (binding — §8.16.4 ROADMAP):

* Default counters: ``maint_ack_total{accepted_by, accepted}``
  Cardinality = consumers × 2.  The ``kind`` label is intentionally
  **dropped** from production metrics; kind-level breakdowns live in
  the audit log (§8.14.1) for postmortem investigation.

* Default latency histogram: ``maint_ack_latency_seconds{accepted_by}``
  10 fixed buckets — operators see distribution per consumer.
  Cardinality = consumers × 10 buckets.

* Debug counter (opt-in): ``maint_ack_total_debug{kind, accepted_by, accepted}``
  Only when ``debug_enabled=True`` (gate: ``cfg.telemetry_debug_enabled``).
  Operators enable for short triage windows; boot guard refuses to raise
  this flag if projected series exceed ``cfg.telemetry_debug_max_series``.

This module is **bus-agnostic** — it holds in-memory counters only.
No Redis, no network, no subprocess.  Callers scrape via the raw dicts.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from common.config import Config

__all__ = [
    "AckMetrics",
    "CardinalityGuardError",
]

# Default histogram bucket boundaries (seconds) — matches Prometheus
# client_python defaults so dashboards can reuse existing queries.
_DEFAULT_BUCKETS: Tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0,
)


class CardinalityGuardError(Exception):
    """Raised when enabling debug mode would exceed the series cap.

    Attributes
    ----------
    projected_series : int
        Worst-case cardinality the guard computed.
    cap : int
        The configured ``telemetry_debug_max_series`` ceiling.
    """

    def __init__(self, projected_series: int, cap: int) -> None:
        self.projected_series = projected_series
        self.cap = cap
        super().__init__(
            f"debug cardinality guard: projected {projected_series} series "
            f"exceeds cap {cap}; refusing to enable debug metrics"
        )


class AckMetrics:
    """In-memory cardinality-safe ack metric collector.

    Parameters
    ----------
    cfg : Config, optional
        Loaded config; defaults to ``Config()`` if *None*.
    debug_enabled : bool, optional
        Override for ``cfg.telemetry_debug_enabled``.  The boot guard
        (``check_debug_cardinality``) is the caller's responsibility —
        this flag is stored as-is.
    buckets : tuple of float, optional
        Histogram bucket boundaries in seconds.  Defaults to
        ``_DEFAULT_BUCKETS``.
    """

    def __init__(
        self,
        cfg: Optional[Config] = None,
        debug_enabled: Optional[bool] = None,
        buckets: Tuple[float, ...] = _DEFAULT_BUCKETS,
    ) -> None:
        self._cfg = cfg or Config()
        self._debug: bool = (
            debug_enabled
            if debug_enabled is not None
            else self._cfg.telemetry_debug_enabled
        )
        self._buckets = buckets

        # counter: (accepted_by, accepted) -> count
        self._ack_total: Dict[Tuple[str, bool], int] = defaultdict(int)

        # latency histogram: accepted_by -> list[float] (raw observations)
        self._ack_latency: Dict[str, List[float]] = defaultdict(list)

        # debug counter: (kind, accepted_by, accepted) -> count
        self._ack_debug: Dict[Tuple[str, str, bool], int] = defaultdict(int)

    # ------------------------------------------------------------------
    # Recording methods
    # ------------------------------------------------------------------

    def record_ack(self, accepted_by: str, accepted: bool) -> None:
        """Increment ``maint_ack_total{accepted_by, accepted}``."""
        self._ack_total[(accepted_by, accepted)] += 1

    def record_ack_latency(self, accepted_by: str, latency_s: float) -> None:
        """Append an observation to ``maint_ack_latency_seconds{accepted_by}``."""
        self._ack_latency[accepted_by].append(latency_s)

    def record_ack_debug(self, kind: str, accepted_by: str, accepted: bool) -> None:
        """Increment the per-kind debug counter (no-op when debug disabled).

        Silent no-op when ``debug_enabled=False`` so callers can call it
        unconditionally without wrapping every site in a conditional.
        """
        if not self._debug:
            return
        self._ack_debug[(kind, accepted_by, accepted)] += 1

    # ------------------------------------------------------------------
    # Cardinality introspection
    # ------------------------------------------------------------------

    def series_count(self, debug: bool = False) -> int:
        """Return the number of distinct label combinations currently seen.

        Parameters
        ----------
        debug : bool
            When *True*, return the debug counter cardinality instead of
            the default counter + histogram cardinality.

        Returns
        -------
        int
            When ``debug=False``: distinct ack_total labels plus one
            bucket row per accepted_by in the latency histogram.
            When ``debug=True``: distinct ack_debug label triples.
        """
        if debug:
            return len(self._ack_debug)
        # Default series: ack_total label combos + latency histogram rows.
        return len(self._ack_total) + len(self._ack_latency) * len(self._buckets)

    # ------------------------------------------------------------------
    # Boot guard (bullet 3)
    # ------------------------------------------------------------------

    def check_debug_cardinality(
        self,
        known_kinds: List[str],
        consumers: List[str],
    ) -> None:
        """Validate that enabling debug mode stays within the series cap.

        Computes the **worst-case** projected series count:
        ``len(known_kinds) × len(consumers) × 2``
        (×2 for the two boolean values of the ``accepted`` label).

        No-op when the instance is not in debug mode.

        Parameters
        ----------
        known_kinds : list of str
            All event kinds the system currently recognises.
        consumers : list of str
            All ack-routing consumer names.

        Raises
        ------
        CardinalityGuardError
            If projected series count exceeds
            ``cfg.telemetry_debug_max_series``.
        """
        if not self._debug:
            return
        projected = len(known_kinds) * len(consumers) * 2
        cap = self._cfg.telemetry_debug_max_series
        if projected > cap:
            raise CardinalityGuardError(projected_series=projected, cap=cap)
