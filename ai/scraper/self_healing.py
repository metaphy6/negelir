"""
Negelir — Self-healing engine + source failover.
Phase 8: Selector fallback, graceful degradation, confidence penalty.
"""

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum

from common.logger import get_logger

log = get_logger("scraper.self_healing")

# ── Selector versioning ──


class SelectorVersionManager:
    """
    Manages versioned selectors per source. On failure, walks backwards
    through fallback_selectors. If all fail, marks source as down.
    """

    def __init__(self, selectors_path: str | None = None):
        if selectors_path is None:
            selectors_path = os.path.join(os.path.dirname(__file__), "selectors.json")
        with open(selectors_path) as f:
            self._config = json.load(f)
        self._sources = self._config.get("sources", {})
        # Track current attempt per source
        self._fallback_index: dict[str, int] = {}

    def get_selectors(self, source: str) -> dict[str, str] | None:
        """Get current (or fallback) selectors for a source."""
        src = self._sources.get(source)
        if not src:
            return None
        idx = self._fallback_index.get(source, -1)
        if idx < 0:
            return src.get("selectors", {})
        fallbacks = src.get("fallback_selectors", [])
        if idx < len(fallbacks):
            return fallbacks[idx].get("selectors", {})
        return None  # all fallbacks exhausted

    def get_version(self, source: str) -> int:
        """Get the version number of the currently active selectors."""
        src = self._sources.get(source)
        if not src:
            return 0
        idx = self._fallback_index.get(source, -1)
        if idx < 0:
            return src.get("version", 1)
        fallbacks = src.get("fallback_selectors", [])
        if idx < len(fallbacks):
            return fallbacks[idx].get("version", 0)
        return 0

    def fallback(self, source: str) -> bool:
        """
        Move to next fallback selector set for the source.
        Returns True if there's a fallback available, False if exhausted.
        """
        src = self._sources.get(source)
        if not src:
            return False
        fallbacks = src.get("fallback_selectors", [])
        idx = self._fallback_index.get(source, -1) + 1
        if idx < len(fallbacks):
            self._fallback_index[source] = idx
            log.warning(
                f"Source {source}: falling back to selector v{fallbacks[idx].get('version', '?')}"
            )
            return True
        self._fallback_index[source] = idx  # store exhausted index
        log.error(f"Source {source}: all selector versions exhausted")
        return False

    def reset(self, source: str):
        """Reset to latest selectors (e.g. after successful scrape)."""
        self._fallback_index.pop(source, None)

    def all_exhausted(self, source: str) -> bool:
        """Check if all selector versions have been tried."""
        src = self._sources.get(source)
        if not src:
            return True
        fallbacks = src.get("fallback_selectors", [])
        idx = self._fallback_index.get(source, -1)
        return idx >= len(fallbacks)

    @property
    def source_names(self) -> list[str]:
        return list(self._sources.keys())


# ── Source status ──

class SourceStatus(Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class SourceState:
    name: str
    status: SourceStatus = SourceStatus.UP
    last_success: float = 0.0
    consecutive_failures: int = 0
    stale_since: float = 0.0  # timestamp when data became stale


# ── Graceful degradation ──

# Priority order for source failover
SOURCE_PRIORITY = ["source_a", "source_b", "source_c", "source_d"]

# Data staleness threshold (7 days in seconds)
STALE_THRESHOLD_SEC = 7 * 24 * 3600

# Confidence penalty multiplier when data is stale
STALE_CONFIDENCE_PENALTY = 0.5

# Consecutive failures before marking source DOWN
FAILURE_THRESHOLD = 3


class SelfHealingEngine:
    """
    Orchestrates selector fallback, source failover, and confidence penalties.
    Graceful degradation chain per roadmap §8.2.
    """

    def __init__(self, selector_mgr: SelectorVersionManager | None = None):
        self.selector_mgr = selector_mgr or SelectorVersionManager()
        self._sources: dict[str, SourceState] = {
            name: SourceState(name=name)
            for name in self.selector_mgr.source_names
        }

    def record_success(self, source: str):
        """Record a successful scrape."""
        state = self._sources.get(source)
        if state:
            state.status = SourceStatus.UP
            state.last_success = time.time()
            state.consecutive_failures = 0
            state.stale_since = 0.0
            self.selector_mgr.reset(source)

    def record_failure(self, source: str) -> SourceStatus:
        """
        Record a scrape failure. Attempt selector fallback.
        Returns the new source status.
        """
        state = self._sources.get(source)
        if not state:
            return SourceStatus.DOWN

        state.consecutive_failures += 1

        if state.consecutive_failures >= FAILURE_THRESHOLD:
            # Try selector fallback
            if self.selector_mgr.fallback(source):
                state.status = SourceStatus.DEGRADED
                state.consecutive_failures = 0  # reset counter for new selectors
                log.warning(f"Source {source}: DEGRADED, trying fallback selectors")
            else:
                state.status = SourceStatus.DOWN
                log.error(f"Source {source}: DOWN — all selectors exhausted")
        elif state.consecutive_failures >= 1:
            state.status = SourceStatus.DEGRADED

        return state.status

    def get_active_sources(self) -> list[str]:
        """
        Return sources in priority order, excluding DOWN sources.
        """
        return [
            name for name in SOURCE_PRIORITY
            if name in self._sources
            and self._sources[name].status != SourceStatus.DOWN
        ]

    def get_source_status(self, source: str) -> SourceStatus:
        state = self._sources.get(source)
        return state.status if state else SourceStatus.DOWN

    def apply_confidence_penalty(self, confidence: float, source: str) -> float:
        """
        Apply confidence penalty when data is stale.
        Per roadmap §8.2: multiply confidence by 0.5 when model is stale.
        """
        state = self._sources.get(source)
        if not state:
            return confidence * STALE_CONFIDENCE_PENALTY

        if state.last_success == 0:
            return confidence * STALE_CONFIDENCE_PENALTY

        age = time.time() - state.last_success
        if age > STALE_THRESHOLD_SEC:
            if state.stale_since == 0.0:
                state.stale_since = time.time()
            return confidence * STALE_CONFIDENCE_PENALTY

        return confidence

    def get_degradation_level(self) -> str:
        """
        Describe current system capability level.
        Per roadmap §8.2 degradation chain.
        """
        active = self.get_active_sources()
        if not active:
            return "complete_data_loss"
        if len(active) == len(SOURCE_PRIORITY):
            return "full_capability"
        down_sources = [
            s for s in SOURCE_PRIORITY
            if s in self._sources and self._sources[s].status == SourceStatus.DOWN
        ]
        if all(s in down_sources for s in ["source_a", "source_b", "source_c"]):
            return "tertiary_only"
        if all(s in down_sources for s in ["source_a", "source_b"]):
            return "turkish_sources_down"
        if "source_a" in down_sources:
            return "primary_down"
        return "partial_degradation"
