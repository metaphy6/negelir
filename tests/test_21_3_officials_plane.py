"""Phase 21.3 — Officials enrichment plane tests.

Tests ≥8 scenarios with ≥2 adversarial cases:
- Rolling stats recomputation on match finalize
- Debouncing of rolling stats in batch cycle
- Home-bias correction clamping
- Last-minute change invalidation
- Duplicate assignment deduplication
- Cards/penalties feature correctness
- Unknown referee rejection (adversarial)
- Last-minute reassignment edge cases
- Warm-start from historical Live data
- Window config boundary cases

Per ROADMAP §21.3 and ENRICHMENT_DATA.md §4.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from ai.common.config import cfg
from ai.common.schemas.records import (
    RefereeAssignmentPayload,
    RefereeProfilePayload,
    RefereeRollingStats,
)
from ai.scraper.extractors.referee_watch import RefereeExtractor, ExtractionError
from ai.scraper.differs.referee_watch import RefereeDiffer
from ai.scraper.enrichment_reactor import RefereeSeason, RefereeEnrichmentReactor


class TestRollingStatsRecomputation:
    """Test rolling-stats recomputation on match finalize."""

    def test_rolling_stats_recomputed_on_match_finalize(self) -> None:
        """Rolling stats should update when a match is finalized."""
        reactor = RefereeEnrichmentReactor(window_size=50)
        season = RefereeSeason()

        # Add 3 matches
        season.add_match(
            match_id="M1",
            yellows=3,
            reds=0,
            penalties=1,
            home_won=True,
            added_time_min=2.5,
        )
        season.add_match(
            match_id="M2",
            yellows=2,
            reds=1,
            penalties=0,
            home_won=False,
            added_time_min=3.0,
        )
        season.add_match(
            match_id="M3",
            yellows=4,
            reds=0,
            penalties=1,
            home_won=True,
            added_time_min=2.0,
        )

        stats = reactor.update_rolling_stats("REF_001", season)

        assert stats["matches_officiated_total"] == 3
        assert stats["matches_officiated_window"] == 3
        assert stats["yellows_per_match"] == pytest.approx((3 + 2 + 4) / 3)
        assert stats["reds_per_match"] == pytest.approx(1 / 3)
        assert stats["penalties_per_match"] == pytest.approx((1 + 0 + 1) / 3)
        assert stats["home_win_pct"] == pytest.approx(2 / 3)
        assert stats["avg_added_time_min"] == pytest.approx((2.5 + 3.0 + 2.0) / 3)

    def test_rolling_stats_debounced_on_batch_finalize(self) -> None:
        """Multiple updates for same referee in batch should be debounced."""
        reactor = RefereeEnrichmentReactor(window_size=50)
        season1 = RefereeSeason()
        season1.add_match(
            match_id="M1",
            yellows=2,
            reds=0,
            penalties=0,
            home_won=True,
            added_time_min=2.0,
        )

        season2 = RefereeSeason()
        season2.add_match(
            match_id="M2",
            yellows=3,
            reds=0,
            penalties=0,
            home_won=False,
            added_time_min=2.5,
        )

        # First call computes and caches
        stats1 = reactor.update_rolling_stats("REF_001", season1)
        assert stats1["yellows_per_match"] == 2.0

        # Second call should return cached result (even though season2 has different data)
        stats2 = reactor.update_rolling_stats("REF_001", season2)
        assert stats2["yellows_per_match"] == 2.0  # Same as first

        # After batch commit, cache clears
        reactor.commit_batch()
        stats3 = reactor.update_rolling_stats("REF_001", season2)
        assert stats3["yellows_per_match"] == 3.0


class TestHomeBiasCorrection:
    """Test home-bias correction clamping."""

    def test_home_bias_correction_clamped_at_configured_threshold(self) -> None:
        """Home-bias correction should be clamped at cfg.enrichment_referee_home_bias_clamp."""
        reactor = RefereeEnrichmentReactor(
            window_size=50,
            home_bias_clamp=0.15,
        )

        # Referee with high home-win rate (70%)
        correction_70 = reactor.compute_home_bias_correction(0.70)
        assert correction_70 == pytest.approx(0.15)  # Clamped

        # Referee with moderate home-win rate (55%)
        correction_55 = reactor.compute_home_bias_correction(0.55)
        assert correction_55 == pytest.approx(0.05)  # 55% - 50%

        # Referee with no home bias (50%)
        correction_50 = reactor.compute_home_bias_correction(0.50)
        assert correction_50 == 0.0

        # Referee with even away bias (45%)
        correction_45 = reactor.compute_home_bias_correction(0.45)
        assert correction_45 == 0.0


class TestLastMinuteChange:
    """Test last-minute change detection and invalidation."""

    def test_last_minute_change_invalidates_derived_features(self) -> None:
        """Last-minute change should trigger feature invalidation."""
        reactor = RefereeEnrichmentReactor(window_size=50)

        fixture_id = "FIXTURE_123"
        # This should log invalidation; no exception raised
        reactor.invalidate_derived_features_for_fixture(fixture_id)

    def test_last_minute_reassignment_sets_flag_only_within_24h(self) -> None:
        """Reassignment flag should only be set if gap < 24h."""
        differ = RefereeDiffer(dedup_window_s=300)
        
        now = datetime.now(timezone.utc)
        
        # First assignment (10 hours before KO)
        prev_payload: RefereeAssignmentPayload = {
            "assignment_id": "A1",
            "fixture_id": "F1",
            "main_referee_id": "REF_A",
            "assistant_referee_ids": [],
            "fourth_official_id": None,
            "var_referee_id": None,
            "avar_referee_id": None,
            "announced_at": (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z"),
            "last_minute_change": False,
        }

        # Reassignment 2 hours later (8 hours before KO) → last_minute_change=true
        new_payload_2h: RefereeAssignmentPayload = {
            "assignment_id": "A2",
            "fixture_id": "F1",
            "main_referee_id": "REF_B",
            "assistant_referee_ids": [],
            "fourth_official_id": None,
            "var_referee_id": None,
            "avar_referee_id": None,
            "announced_at": (now - timedelta(hours=8)).isoformat().replace("+00:00", "Z"),
            "last_minute_change": False,
        }

        result_2h = differ.process_change(new_payload_2h, prev_payload)
        assert result_2h["is_last_minute"] is True

        # Reassignment 30 hours later (outside 24h window) → last_minute_change=false
        new_payload_30h: RefereeAssignmentPayload = {
            "assignment_id": "A3",
            "fixture_id": "F1",
            "main_referee_id": "REF_C",
            "assistant_referee_ids": [],
            "fourth_official_id": None,
            "var_referee_id": None,
            "avar_referee_id": None,
            "announced_at": (now - timedelta(hours=-20)).isoformat().replace("+00:00", "Z"),
            "last_minute_change": False,
        }

        result_30h = differ.process_change(new_payload_30h, prev_payload)
        assert result_30h["is_last_minute"] is False


class TestDuplicateHandling:
    """Test duplicate assignment deduplication."""

    def test_duplicate_assignment_treated_as_update_within_dedup_window(self) -> None:
        """Duplicate assignments within dedup window should be treated as updates."""
        differ = RefereeDiffer(dedup_window_s=300)

        now = datetime.now(timezone.utc)

        # First assignment
        prev_payload: RefereeAssignmentPayload = {
            "assignment_id": "A1",
            "fixture_id": "F1",
            "main_referee_id": "REF_001",
            "assistant_referee_ids": ["REF_002"],
            "fourth_official_id": None,
            "var_referee_id": None,
            "avar_referee_id": None,
            "announced_at": now.isoformat().replace("+00:00", "Z"),
            "last_minute_change": False,
        }

        # Duplicate within 5 min (same announced_at)
        new_payload: RefereeAssignmentPayload = {
            "assignment_id": "A1_DUP",
            "fixture_id": "F1",
            "main_referee_id": "REF_001",
            "assistant_referee_ids": ["REF_002"],
            "fourth_official_id": None,
            "var_referee_id": None,
            "avar_referee_id": None,
            "announced_at": now.isoformat().replace("+00:00", "Z"),
            "last_minute_change": False,
        }

        result = differ.process_change(new_payload, prev_payload)
        assert result["is_duplicate"] is True
        assert result["change_type"] == "duplicate"


class TestExtractionErrors:
    """Adversarial test: unknown referee rejection."""

    def test_unknown_referee_id_raises_extraction_error(self) -> None:
        """Extractor should reject unknown referee IDs during normal operation."""
        extractor = RefereeExtractor(known_referee_ids={"REF_001", "REF_002"})

        with pytest.raises(ExtractionError, match="Unknown referee_id"):
            extractor.extract_assignment(
                assignment_id="A1",
                fixture_id="F1",
                main_referee_id="REF_UNKNOWN",
                assistant_ids=[],
                fourth_official_id=None,
                var_referee_id=None,
                avar_referee_id=None,
                announced_at="2026-06-20T10:00:00Z",
            )

    def test_unmapped_conditions_string_raises_extraction_error(self) -> None:
        """Adversarial: invalid data structures should raise ExtractionError."""
        extractor = RefereeExtractor(known_referee_ids={"REF_001"})

        # Missing main_referee_id
        bad_data = {
            "assignment_id": "A1",
            "announced_at": "2026-06-20T10:00:00Z",
            # Missing: main_referee
        }

        with pytest.raises(ExtractionError, match="Missing main_referee"):
            extractor.extract_from_tff_json(bad_data, "F1")


class TestWarmStart:
    """Test rolling-stats warm-start from historical Live data."""

    def test_rolling_stats_warm_start_computes_correct_stats_from_historical_plane_3_data(
        self,
    ) -> None:
        """Warm-start should bootstrap stats correctly from Live plane records."""
        reactor = RefereeEnrichmentReactor(window_size=50)

        # Simulate 5 historical match records from Live plane
        live_records = [
            {
                "match_stable_id": "M1",
                "status": "finished",
                "referee_id": "REF_A",
                "total_yellows": 3,
                "total_reds": 0,
                "total_penalties": 1,
                "home": {"score": 2},
                "away": {"score": 1},
                "added_time_min": 2.0,
            },
            {
                "match_stable_id": "M2",
                "status": "finished",
                "referee_id": "REF_A",
                "total_yellows": 2,
                "total_reds": 1,
                "total_penalties": 0,
                "home": {"score": 1},
                "away": {"score": 1},
                "added_time_min": 3.0,
            },
            {
                "match_stable_id": "M3",
                "status": "finished",
                "referee_id": "REF_B",
                "total_yellows": 4,
                "total_reds": 0,
                "total_penalties": 2,
                "home": {"score": 0},
                "away": {"score": 2},
                "added_time_min": 1.5,
            },
        ]

        seasons = reactor.warm_start_from_live_plane(live_records)

        assert len(seasons) == 2
        assert "REF_A" in seasons
        assert "REF_B" in seasons

        # Verify REF_A stats
        ref_a_stats = seasons["REF_A"].compute_rolling_stats(50)
        assert ref_a_stats["matches_officiated_total"] == 2
        assert ref_a_stats["yellows_per_match"] == pytest.approx((3 + 2) / 2)
        assert ref_a_stats["reds_per_match"] == pytest.approx(1 / 2)
        assert ref_a_stats["home_win_pct"] == pytest.approx(1 / 2)  # Won 1 of 2

        # Verify REF_B stats
        ref_b_stats = seasons["REF_B"].compute_rolling_stats(50)
        assert ref_b_stats["matches_officiated_total"] == 1
        assert ref_b_stats["yellows_per_match"] == 4.0
        assert ref_b_stats["home_win_pct"] == 0.0  # Home lost

    def test_warm_start_respects_referee_window_matches_config(self) -> None:
        """Warm-start should respect cfg.enrichment_referee_window_matches."""
        reactor = RefereeEnrichmentReactor(window_size=3)

        # Create 10 historical records for one referee
        live_records = [
            {
                "match_stable_id": f"M{i}",
                "status": "finished",
                "referee_id": "REF_A",
                "total_yellows": 2 + i,
                "total_reds": 0,
                "total_penalties": 1,
                "home": {"score": 1},
                "away": {"score": 0},
                "added_time_min": 2.0,
            }
            for i in range(10)
        ]

        seasons = reactor.warm_start_from_live_plane(live_records)
        ref_a_stats = seasons["REF_A"].compute_rolling_stats(3)

        # Window is 3, so only last 3 matches should count
        assert ref_a_stats["matches_officiated_window"] == 3
        assert ref_a_stats["matches_officiated_total"] == 10

        # Last 3 matches have yellows = [9, 10, 11], so avg = 10.0
        assert ref_a_stats["yellows_per_match"] == pytest.approx(10.0)


class TestCardsAndPenaltyFeatures:
    """Test cards/penalty feature correctness."""

    def test_cards_and_penalty_features_correct_for_known_referee(self) -> None:
        """Card/penalty features should be accurate for known referees."""
        season = RefereeSeason()

        # Add 5 matches with varied card rates
        for i in range(5):
            season.add_match(
                match_id=f"M{i}",
                yellows=2 + i,  # 2, 3, 4, 5, 6
                reds=i % 2,  # 0, 1, 0, 1, 0
                penalties=1 if i < 3 else 0,
                home_won=True,
                added_time_min=2.5,
            )

        stats = season.compute_rolling_stats(50)

        yellows = sum(2 + i for i in range(5))  # 2 + 3 + 4 + 5 + 6 = 20
        assert stats["yellows_per_match"] == pytest.approx(yellows / 5)

        reds = sum(i % 2 for i in range(5))  # 0 + 1 + 0 + 1 + 0 = 2
        assert stats["reds_per_match"] == pytest.approx(reds / 5)

        penalties = 3  # First 3 matches
        assert stats["penalties_per_match"] == pytest.approx(penalties / 5)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
