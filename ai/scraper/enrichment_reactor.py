"""Phase 21.3 — Enrichment reactor for rolling stats (officials plane).

Handles:
- Rolling-stats recomputation on match finalize (debounced per CONTENT_FRESHNESS §15)
- Warm-start replay from Live plane on first deployment
- Home-bias correction computation
- Last-minute change invalidation of derived features

Per ENRICHMENT_DATA.md §4.3–§4.4 and CONTENT_FRESHNESS.md §15.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import defaultdict
import logging

from ai.common.config import cfg
from ai.common.logger import get_logger
from ai.common.schemas.records import RefereeAssignmentPayload, RefereeProfilePayload, RefereeRollingStats

log = get_logger("scraper.enrichment_reactor")


@dataclass
class RefereeSeason:
    """Per-referee season statistics (for rolling-stats computation)."""
    
    matches: List[Dict[str, Any]] = field(default_factory=list)
    """List of officiated match records (from Live plane / match finalization events)."""
    
    total_yellows: float = 0.0
    total_reds: float = 0.0
    total_penalties: float = 0.0
    home_wins: int = 0
    home_total: int = 0
    total_added_time_min: float = 0.0
    
    def add_match(
        self,
        match_id: str,
        yellows: int,
        reds: int,
        penalties: int,
        home_won: bool,
        added_time_min: float,
    ) -> None:
        """Add a finalized match to the referee's season data."""
        self.matches.append({
            "match_id": match_id,
            "yellows": yellows,
            "reds": reds,
            "penalties": penalties,
            "home_won": home_won,
            "added_time_min": added_time_min,
        })
        self.total_yellows += yellows
        self.total_reds += reds
        self.total_penalties += penalties
        if home_won:
            self.home_wins += 1
        self.home_total += 1
        self.total_added_time_min += added_time_min

    def compute_rolling_stats(self, window_size: int) -> RefereeRollingStats:
        """Compute rolling stats from the last window_size matches."""
        if not self.matches:
            return {
                "matches_officiated_total": 0,
                "matches_officiated_window": 0,
                "yellows_per_match": 0.0,
                "reds_per_match": 0.0,
                "penalties_per_match": 0.0,
                "home_win_pct": 0.0,
                "avg_added_time_min": 0.0,
            }

        total = len(self.matches)
        window_matches = self.matches[-window_size:] if len(self.matches) > window_size else self.matches
        window_count = len(window_matches)

        window_yellows = sum(m["yellows"] for m in window_matches)
        window_reds = sum(m["reds"] for m in window_matches)
        window_penalties = sum(m["penalties"] for m in window_matches)
        window_home_wins = sum(1 for m in window_matches if m["home_won"])
        window_added_time = sum(m["added_time_min"] for m in window_matches)

        return {
            "matches_officiated_total": total,
            "matches_officiated_window": window_count,
            "yellows_per_match": window_yellows / window_count if window_count > 0 else 0.0,
            "reds_per_match": window_reds / window_count if window_count > 0 else 0.0,
            "penalties_per_match": window_penalties / window_count if window_count > 0 else 0.0,
            "home_win_pct": window_home_wins / window_count if window_count > 0 else 0.0,
            "avg_added_time_min": window_added_time / window_count if window_count > 0 else 0.0,
        }


@dataclass
class RefereeEnrichmentReactor:
    """Reactor for referee rolling-stats computation and warm-start.
    
    Per ENRICHMENT_DATA.md §4.3–§4.4:
    - Rolling-stats reactor recomputes on every officiated-fixture score event
    - Debounced: multiple score events for same referee in one batch → one recompute
    - Home-bias: when home_win_pct > cfg.referee_home_bias_clamp, apply Elo nudge at predict-time
    - Warm-start: replay Live plane on first deployment to bootstrap rolling-stats
    """

    window_size: int = field(default_factory=lambda: cfg.enrichment_referee_window_matches)
    home_bias_clamp: float = field(default_factory=lambda: cfg.enrichment_referee_home_bias_clamp)
    debounce_cache: Dict[str, RefereeRollingStats] = field(default_factory=dict)
    """Per-referee cache of rolling-stats in current batch; cleared after batch commit."""

    def update_rolling_stats(
        self,
        referee_id: str,
        season: RefereeSeason,
    ) -> RefereeRollingStats:
        """Compute and cache rolling stats for a referee.
        
        Debouncing: multiple calls for same referee in one batch reuse cached result.
        Per CONTENT_FRESHNESS.md §15.
        """
        if referee_id in self.debounce_cache:
            log.debug(f"Reusing cached rolling-stats for referee {referee_id} (debounced)")
            return self.debounce_cache[referee_id]

        stats = season.compute_rolling_stats(self.window_size)
        self.debounce_cache[referee_id] = stats
        log.debug(f"Computed rolling-stats for referee {referee_id}: {stats['matches_officiated_window']} window")
        return stats

    def commit_batch(self) -> None:
        """Clear debounce cache after batch is committed."""
        log.debug(f"Clearing debounce cache ({len(self.debounce_cache)} entries)")
        self.debounce_cache.clear()

    def compute_home_bias_correction(self, home_win_pct: float) -> float:
        """Compute home-bias correction factor.
        
        When home_win_pct > cfg.referee_home_bias_clamp, the referee exhibits
        anomalous home bias. Clamped to [0, cfg.referee_home_bias_clamp].
        
        Returns: correction factor (0.0 = no correction, up to clamp value).
        """
        if home_win_pct > self.home_bias_clamp:
            correction = min(home_win_pct - 0.5, self.home_bias_clamp)
            return max(0.0, correction)
        return 0.0

    def warm_start_from_live_plane(
        self,
        live_records: List[Dict[str, Any]],
    ) -> Dict[str, RefereeSeason]:
        """Replay Live plane records to bootstrap rolling-stats.
        
        Called once on first deployment when referee_profiles table is empty.
        Processes all score records for matches this season, extracting referee
        match statistics.
        
        Args:
            live_records: List of score records from Live plane (sorted by time).

        Returns:
            Dict[referee_id → RefereeSeason] with bootstrapped stats.
        """
        seasons: Dict[str, RefereeSeason] = defaultdict(RefereeSeason)

        for record in live_records:
            try:
                match_id = record.get("match_stable_id", "")
                status = record.get("status", "")

                # Only process finalized matches
                if status != "finished":
                    continue

                referee_id = record.get("referee_id")
                if not referee_id:
                    continue

                yellows = record.get("total_yellows", 0)
                reds = record.get("total_reds", 0)
                penalties = record.get("total_penalties", 0)

                home_score = record.get("home", {}).get("score", 0)
                away_score = record.get("away", {}).get("score", 0)
                home_won = home_score > away_score

                added_time_min = record.get("added_time_min", 0.0)

                seasons[referee_id].add_match(
                    match_id=match_id,
                    yellows=yellows,
                    reds=reds,
                    penalties=penalties,
                    home_won=home_won,
                    added_time_min=added_time_min,
                )

            except Exception as e:
                log.warning(f"Error processing Live record for warm-start: {e}")
                continue

        log.info(f"Warm-start: bootstrapped stats for {len(seasons)} referees from {len(live_records)} records")
        return seasons

    def invalidate_derived_features_for_fixture(self, fixture_id: str) -> None:
        """Invalidate cached cards/penalty features for a fixture (on last_minute_change).
        
        Per ENRICHMENT_DATA.md §4.4: when a last-minute reassignment occurs,
        clear cached derived features so they are recomputed with new assignment.
        
        This is a hook for the scheduler to queue a recompute.
        """
        log.info(f"Invalidating derived features for fixture {fixture_id} due to last-minute reassignment")
        # Implementation: enqueue fixture_id to the feature recompute queue
        # (details in §21.19 enrichment batch cycle)
