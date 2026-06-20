"""
Negelir — Source health monitor.
Phase 4: Tracks scrape success/failure per source.
Declares source DOWN after consecutive failures exceed threshold.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field

from ai.common.config import cfg
from ai.common.logger import get_logger

log = get_logger("scraper.health")


@dataclass
class HealthRecord:
    """Single health check record."""
    success: bool
    matches_found: int = 0
    timestamp: float = field(default_factory=time.time)


class SourceHealthMonitor:
    """
    Monitors scrape source health.
    Declares a source DOWN after `cfg.source_failure_threshold` consecutive failures.
    """

    def __init__(self, failure_threshold: int | None = None):
        self.failure_threshold = (
            failure_threshold if failure_threshold is not None
            else cfg.source_failure_threshold
        )
        self._history: dict[str, list[HealthRecord]] = defaultdict(list)
        self._down_sources: set[str] = set()

    def record(self, source: str, success: bool, matches_found: int = 0):
        """Record a scrape attempt outcome."""
        self._history[source].append(HealthRecord(
            success=success, matches_found=matches_found
        ))
        recent = self._history[source][-self.failure_threshold:]
        if len(recent) >= self.failure_threshold and all(not r.success for r in recent):
            if source not in self._down_sources:
                self._declare_failure(source)

    def _declare_failure(self, source: str):
        """Mark source as DOWN."""
        self._down_sources.add(source)
        log.warning(f"Source declared DOWN: {source} ({self.failure_threshold} consecutive failures)")

    def is_healthy(self, source: str) -> bool:
        """Check if source is considered healthy."""
        return source not in self._down_sources

    def mark_recovered(self, source: str):
        """Mark a previously-down source as recovered."""
        self._down_sources.discard(source)
        log.info(f"Source recovered: {source}")

    def get_down_sources(self) -> set[str]:
        """Return set of currently-down source names."""
        return set(self._down_sources)

    def get_history(self, source: str) -> list[HealthRecord]:
        """Return health check history for a source."""
        return list(self._history[source])

    def success_rate(self, source: str, window: int = 10) -> float:
        """Calculate success rate over recent window."""
        recent = self._history[source][-window:]
        if not recent:
            return 1.0  # no data = assume healthy
        return sum(1 for r in recent if r.success) / len(recent)
