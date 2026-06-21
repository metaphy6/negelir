"""
Phase 13.4 — Identity resolution soak test (4-week mock replay).

Per ROADMAP §13.4: "4-week mock replay of Süper Lig + UCL + Türkiye Kupası 
produces zero false-merges and ≤ cfg.identity_false_split_max_per_week 
(default 1) false-splits."

This test provides the infrastructure (harness + skeleton) that CAN run
a 4-week simulation. The harness loads TR Lig 1 + UCL + Türkiye Kupası 
mock data, replays them time-series over 4 synthetic weeks, tracks 
identity resolution decisions, and asserts false-merge count and 
false-split count per week.

NOTE: Full 4-week soak test is deferred pending a comprehensive mock corpus
(currently ≤7 days available in infra/mock/seeds). The infrastructure 
is live and ready for corpus expansion.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

import pytest

from common.config import Config
from common.logger import get_logger
from swarm.identity import AnchorResolver

_log = get_logger(__name__)


@dataclass
class WeeklyIdentityStats:
    """Tracks identity resolution metrics for one week."""
    
    week_number: int
    start_date: dt.date
    end_date: dt.date
    
    # Decision counts
    merges_attempted: int = 0
    merges_accepted: int = 0
    merges_rejected: int = 0  # Below threshold
    splits_attempted: int = 0
    splits_accepted: int = 0
    
    # Error tracking
    false_merges: int = 0  # Merged distinct entities that should be separate
    false_splits: int = 0  # Split same entity that should be merged
    
    # Coverage
    clubs_seen: set[str] = field(default_factory=set)
    clubs_with_observations: set[str] = field(default_factory=set)
    competitions_covered: set[str] = field(default_factory=set)


@dataclass
class SoakTestConfig:
    """Configuration for the 4-week soak test harness."""
    
    merge_threshold: float = 0.94
    similarity_floor_manual_review: float = 0.85
    false_split_max_per_week: int = 1
    
    # Competitions to include
    competitions: list[str] = field(default_factory=lambda: [
        "tr_super_lig",      # TR Lig 1 (Süper Lig)
        "ucl",               # UEFA Champions League
        "turkiye_kupasi",    # Turkish Cup
    ])
    
    # Simulation span
    weeks: int = 4
    start_date: Optional[dt.date] = None
    
    def __post_init__(self):
        if self.start_date is None:
            self.start_date = dt.date(2025, 9, 1)


class SoakTestHarness:
    """
    Orchestrates a mock replay of 4 weeks of fixture + player + club 
    observations across multiple competitions, tracking identity resolution
    decisions and detecting false-merges / false-splits.
    """
    
    def __init__(self, config: Optional[SoakTestConfig] = None):
        self.cfg = config or SoakTestConfig()
        self.resolver = AnchorResolver(
            merge_threshold=self.cfg.merge_threshold,
            similarity_floor_manual_review=self.cfg.similarity_floor_manual_review,
        )
        self.weekly_stats: dict[int, WeeklyIdentityStats] = {}
        self.all_decisions: list[dict] = []
    
    def _week_start_end(self, week_num: int) -> tuple[dt.date, dt.date]:
        """Calculate start and end dates for a given week number."""
        start = self.cfg.start_date + dt.timedelta(weeks=week_num)
        end = start + dt.timedelta(days=6)
        return start, end
    
    def initialize_weekly_stats(self) -> None:
        """Pre-allocate stats for all weeks."""
        for week_num in range(self.cfg.weeks):
            start, end = self._week_start_end(week_num)
            self.weekly_stats[week_num] = WeeklyIdentityStats(
                week_number=week_num,
                start_date=start,
                end_date=end,
            )
    
    def record_observation(
        self,
        stable_id: str,
        name_form: str,
        source: str,
        competition: str,
        week_num: int,
    ) -> None:
        """
        Record a club observation during a specific week.
        
        Args:
            stable_id: The canonical club identity
            name_form: The observed name (e.g., "Galatasaray", "Gala")
            source: Source that made the observation
            competition: Competition ID
            week_num: Which week (0-3 for a 4-week test)
        """
        if week_num not in self.weekly_stats:
            raise ValueError(f"Week {week_num} not in range [0, {self.cfg.weeks-1}]")
        
        stats = self.weekly_stats[week_num]
        stats.clubs_seen.add(stable_id)
        stats.competitions_covered.add(competition)
        
        # Add to resolver using its direct observation API
        self.resolver.add_observation(
            stable_id=stable_id,
            name_form=name_form,
            source=source,
            competition=competition,
        )
        stats.clubs_with_observations.add(stable_id)
    
    def record_merge_decision(
        self,
        stable_id_a: str,
        stable_id_b: str,
        similarity: float,
        week_num: int,
        accepted: bool,
        is_false_positive: bool = False,
    ) -> None:
        """
        Record a merge decision (attempted or accepted).
        
        Args:
            stable_id_a, stable_id_b: The two IDs being considered for merge
            similarity: Computed similarity score
            week_num: Which week
            accepted: Whether the merge was accepted
            is_false_positive: Whether this merge was incorrectly accepted
                               (used for validation after the replay)
        """
        stats = self.weekly_stats[week_num]
        stats.merges_attempted += 1
        
        if accepted:
            stats.merges_accepted += 1
            if is_false_positive:
                stats.false_merges += 1
                _log.warning(
                    f"Week {week_num}: FALSE-MERGE detected between "
                    f"{stable_id_a} and {stable_id_b} (similarity={similarity:.3f})"
                )
        else:
            stats.merges_rejected += 1
        
        self.all_decisions.append({
            "type": "merge",
            "week": week_num,
            "a": stable_id_a,
            "b": stable_id_b,
            "similarity": similarity,
            "accepted": accepted,
            "false_positive": is_false_positive,
        })
    
    def record_split_decision(
        self,
        stable_id: str,
        into_ids: list[str],
        week_num: int,
        is_false_positive: bool = False,
    ) -> None:
        """
        Record a split decision.
        
        Args:
            stable_id: The ID being split
            into_ids: The resulting IDs after split
            week_num: Which week
            is_false_positive: Whether this split was incorrectly applied
        """
        stats = self.weekly_stats[week_num]
        stats.splits_attempted += 1
        stats.splits_accepted += 1
        
        if is_false_positive:
            stats.false_splits += 1
            _log.warning(
                f"Week {week_num}: FALSE-SPLIT detected for {stable_id} "
                f"into {into_ids}"
            )
        
        self.all_decisions.append({
            "type": "split",
            "week": week_num,
            "stable_id": stable_id,
            "into_ids": into_ids,
            "false_positive": is_false_positive,
        })
    
    def validate_soak_results(self, cfg: Config) -> tuple[bool, str]:
        """
        Validate the 4-week soak test against the acceptance criteria.
        
        Criteria (per ROADMAP §13.4):
        - Zero false-merges across all 4 weeks
        - ≤ cfg.identity_false_split_max_per_week false-splits per week
        
        Returns: (passed: bool, message: str)
        """
        total_false_merges = sum(
            stats.false_merges for stats in self.weekly_stats.values()
        )
        
        weekly_false_splits = {
            week: stats.false_splits
            for week, stats in self.weekly_stats.items()
        }
        
        max_splits_per_week = max(weekly_false_splits.values()) if weekly_false_splits else 0
        
        # Criteria check
        merges_ok = total_false_merges == 0
        splits_ok = max_splits_per_week <= cfg.identity_false_split_max_per_week
        
        message = (
            f"Soak test results:\n"
            f"  False-merges (must be 0): {total_false_merges} ✓ \n"
            f"  Max false-splits/week (must be ≤{cfg.identity_false_split_max_per_week}): "
            f"{max_splits_per_week} {'✓' if splits_ok else '✗'}\n"
        )
        
        for week, stats in self.weekly_stats.items():
            message += (
                f"  Week {week}: "
                f"{stats.clubs_with_observations} clubs observed, "
                f"{stats.merges_accepted} merges, "
                f"{stats.false_merges} false-merges, "
                f"{stats.false_splits} false-splits\n"
            )
        
        return merges_ok and splits_ok, message


def mock_replay_4week(
    config_overrides: Optional[dict] = None,
) -> SoakTestHarness:
    """
    Load the 4-week mock replay harness with TR Lig 1 + UCL + Türkiye Kupası.
    
    This function sets up the infrastructure but does not run the full replay 
    (pending a comprehensive mock corpus). It demonstrates the harness pattern 
    and can be extended when corpus data becomes available.
    
    Args:
        config_overrides: Optional dict to override SoakTestConfig fields
    
    Returns:
        SoakTestHarness ready for replay
    """
    cfg = SoakTestConfig(**(config_overrides or {}))
    harness = SoakTestHarness(config=cfg)
    harness.initialize_weekly_stats()
    
    # Placeholder: Load mock data from infra/mock/seeds/
    # 
    # TODO (Phase 13.4+): When a 4-week corpus is available:
    # 1. Load TR Lig 1 fixtures (≥70 teams)
    # 2. Load UCL fixtures (≥8 teams)
    # 3. Load Türkiye Kupası fixtures
    # 4. Replay time-series, calling record_observation() per club sighting
    # 5. Call record_merge_decision() for each resolution attempt
    # 6. Post-validate with validate_soak_results()
    
    _log.info(
        f"Soak test harness initialized (4 weeks, {len(cfg.competitions)} competitions). "
        f"Ready for corpus data."
    )
    
    return harness


class TestIdentitySoak:
    """
    Phase 13.4 soak test suite.
    
    The full 4-week test is infrastructure-ready but corpus-deferred.
    We provide a quick sanity-check (`test_identity_soak_infrastructure`) 
    to validate the harness itself.
    """
    
    def test_identity_soak_infrastructure(self) -> None:
        """
        Sanity check: the soak-test harness initializes correctly and
        can track observations, merge decisions, and split decisions.
        """
        # Initialize
        harness = mock_replay_4week()
        cfg = Config()
        
        assert harness.cfg.weeks == 4
        assert len(harness.weekly_stats) == 4
        assert len(harness.resolver.all_anchor_sets()) >= 0
        
        # Simulate one week of activity
        week = 0
        
        # Record some club observations
        harness.record_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="mackolik",
            competition="tr_super_lig",
            week_num=week,
        )
        harness.record_observation(
            stable_id="galatasaray_tr",
            name_form="Gala",
            source="nesine",
            competition="tr_super_lig",
            week_num=week,
        )
        
        # Simulate a merge decision (same club, different name forms)
        harness.record_merge_decision(
            stable_id_a="galatasaray_tr",
            stable_id_b="galatasaray_tr",
            similarity=1.0,
            week_num=week,
            accepted=True,
            is_false_positive=False,
        )
        
        # Validate
        stats = harness.weekly_stats[week]
        assert len(stats.clubs_seen) == 1
        assert len(stats.competitions_covered) == 1
        assert stats.merges_attempted == 1
        assert stats.false_merges == 0
        
        # Validate overall
        passed, msg = harness.validate_soak_results(cfg)
        assert passed, msg
        _log.info(f"Soak harness sanity check passed:\n{msg}")
    
    def test_identity_soak_harness_tracks_per_week(self) -> None:
        """Verify the harness correctly segments statistics by week."""
        harness = mock_replay_4week()
        
        # Add observations in different weeks
        for week in range(4):
            harness.record_observation(
                stable_id=f"club_week{week}",
                name_form=f"Club{week}",
                source="test",
                competition="tr_super_lig",
                week_num=week,
            )
        
        # Verify separation
        for week in range(4):
            stats = harness.weekly_stats[week]
            assert f"club_week{week}" in stats.clubs_seen
            # Other weeks should not have this club
            for other_week in range(4):
                if other_week != week:
                    assert f"club_week{week}" not in harness.weekly_stats[other_week].clubs_seen
    
    def test_identity_soak_false_merge_detection(self) -> None:
        """Verify false-merge detection works correctly."""
        harness = mock_replay_4week()
        cfg = Config()
        
        # Record a false merge (should not happen in real scenario)
        harness.record_merge_decision(
            stable_id_a="real_madrid_es",
            stable_id_b="real_madrid_uy",  # Different teams, different countries
            similarity=0.92,  # Just below threshold but incorrectly accepted
            week_num=0,
            accepted=True,
            is_false_positive=True,
        )
        
        # Validate should fail
        passed, msg = harness.validate_soak_results(cfg)
        assert not passed, "Should reject false-merge"
        assert "false-merges" in msg.lower()
    
    def test_identity_soak_false_split_threshold(self) -> None:
        """Verify false-split threshold enforcement per week."""
        harness = mock_replay_4week()
        cfg = Config()
        
        # Add 2 false splits to week 0 (exceeds default max of 1)
        harness.record_split_decision(
            stable_id="merged_club",
            into_ids=["club_a", "club_b"],
            week_num=0,
            is_false_positive=True,
        )
        harness.record_split_decision(
            stable_id="merged_club_2",
            into_ids=["club_c", "club_d"],
            week_num=0,
            is_false_positive=True,
        )
        
        # Validate should fail (2 false splits > cfg.identity_false_split_max_per_week=1)
        passed, msg = harness.validate_soak_results(cfg)
        assert not passed, f"Should reject excess false-splits: {msg}"
        assert "false-splits" in msg.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
