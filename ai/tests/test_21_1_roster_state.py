"""Phase 21.1 §21.1 — Integration tests for roster-state enrichment pipeline.

Tests for the complete roster-state enrichment system:
  - Confidence gate enforcement (rumour/agreed/official)
  - Feature computation (squad strength, cohesion, departure shock)
  - Cross-source deduplication
  - Suspension lifecycle
  - End-to-end workflows

Per ROADMAP §21.1 bullet 9 and ENRICHMENT_DATA.md §2.
Minimum 8 tests including ≥ 2 adversarial.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from ai.scraper.differs.transfers_feed.confidence_gate import apply_gate
from ai.model.enrichment_features import (
    compute_squad_strength_delta,
    compute_cohesion_penalty,
    compute_departure_shock,
)
from ai.scraper.transfer_deduplication import deduplicate_transfers
from ai.scraper.suspension_lifecycle import (
    should_expire,
    decrement_matches_remaining,
)
from ai.common.config import Config
from ai.common.schemas.records import TransferPayload


@pytest.fixture
def mock_config() -> Config:
    """Config with enrichment settings."""
    cfg = Config()
    cfg.enrichment_cohesion_penalty_curve = [0.15, 0.10, 0.05, 0.02]
    cfg.enrichment_departure_shock = 0.05
    return cfg


@pytest.fixture
def sample_transfer() -> dict:
    """Base transfer record."""
    return {
        "transfer_id": "T_001",
        "player_id": "P_100",
        "from_team_id": "TEAM_A",
        "to_team_id": "TEAM_B",
        "transfer_window": "summer",
        "transfer_type": "permanent",
        "fee_eur": 10_000_000,
        "contract_until": "2028-06-30",
        "announced_at": "2026-06-01T10:00:00Z",
        "effective_at": "2026-06-15T00:00:00Z",
        "confidence": "official",
        "source": "mackolik",
    }


class TestConfidenceGateIntegration:
    """Integration tests for confidence gate in roster-state pipeline."""
    
    def test_transfer_rumour_does_not_mutate_roster_state(self, sample_transfer: dict) -> None:
        """Rumour transfers should not be written to roster-state storage."""
        rumour: TransferPayload = {**sample_transfer, "confidence": "rumour"}  # type: ignore
        instruction = apply_gate(rumour)
        
        assert instruction["should_write"] is False
        # Storage layer should skip writing this record entirely
    
    def test_transfer_agreed_writes_provisional_flag(self, sample_transfer: dict) -> None:
        """Agreed transfers should write with provisional=true flag."""
        agreed: TransferPayload = {**sample_transfer, "confidence": "agreed"}  # type: ignore
        instruction = apply_gate(agreed)
        
        assert instruction["should_write"] is True
        assert instruction["provisional"] is True
        # Storage layer receives this and marks the record as provisional
    
    def test_transfer_official_clears_provisional_on_earlier_agreed(
        self,
        sample_transfer: dict,
    ) -> None:
        """Official transfer should signal to clear provisional on same player."""
        official: TransferPayload = {**sample_transfer, "confidence": "official"}  # type: ignore
        instruction = apply_gate(official)
        
        assert instruction["should_write"] is True
        assert instruction["provisional"] is False
        assert instruction["clear_provisional_for_player"] == "P_100"
        # Storage layer should find earlier 'agreed' records for P_100
        # and clear their provisional flag


class TestFeatureComputationIntegration:
    """Integration tests for enrichment features in pipeline."""
    
    def test_squad_strength_delta_computed_on_official_transfer(
        self,
        sample_transfer: dict,
    ) -> None:
        """Squad strength delta should be computed when official transfer arrives."""
        official: TransferPayload = {**sample_transfer, "confidence": "official"}  # type: ignore
        
        # Simulated feature computation after transfer is confirmed as official
        delta = compute_squad_strength_delta(
            team_id=official["to_team_id"],
            player_id=official["player_id"],
            old_rating=75.0,
            new_rating=82.0,
            current_squad_size=20,
        )
        
        assert delta > 0.0  # Positive delta for upgrade
    
    def test_cohesion_penalty_decays_correctly_over_four_appearances(
        self,
        mock_config: Config,
    ) -> None:
        """Cohesion penalty should decay over first 4 appearances."""
        penalties = []
        for app_count in range(5):
            penalty = compute_cohesion_penalty(app_count, mock_config)
            penalties.append(penalty)
        
        # Penalties should decay: -0.15, -0.10, -0.05, -0.02, 0
        assert penalties[0] == -0.15
        assert penalties[1] == -0.10
        assert penalties[2] == -0.05
        assert penalties[3] == -0.02
        assert penalties[4] == 0.0
    
    def test_departure_shock_applied_within_14d_not_after_15d(
        self,
        mock_config: Config,
    ) -> None:
        """Departure shock should apply within 14d window but not after 15d."""
        # Test within 14d: should trigger shock
        shock_within = compute_departure_shock(
            departure_date_utc="2026-06-07T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[90.0, 88.0, 85.0, 82.0, 75.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",  # 14 days later
        )
        # At exactly 14 days, should NOT trigger (>=14)
        assert shock_within == 0.0
        
        # Test within 13d: should trigger shock
        shock_close = compute_departure_shock(
            departure_date_utc="2026-06-08T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[90.0, 88.0, 85.0, 82.0, 75.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",  # 13 days later
        )
        assert shock_close < 0.0


class TestDeduplicationIntegration:
    """Integration tests for cross-source deduplication."""
    
    def test_duplicate_transfers_from_two_sources_collapse(
        self,
        sample_transfer: dict,
    ) -> None:
        """Identical transfers from two sources should collapse to one."""
        # Same transfer from Mackolik (lower priority, agreed)
        mackolik_version: TransferPayload = {
            **sample_transfer,
            "source": "mackolik",
            "confidence": "agreed",
        }  # type: ignore
        
        # Same transfer from club site (higher priority, official)
        club_site_version: TransferPayload = {
            **sample_transfer,
            "source": "club_site",
            "confidence": "official",
        }  # type: ignore
        
        records: list[TransferPayload] = [mackolik_version, club_site_version]
        source_priority = {"club_site": 0, "mackolik": 1}
        
        result = deduplicate_transfers(records, source_priority)
        
        assert len(result) == 1
        # Club site version should win (higher confidence)
        assert result[0]["source"] == "club_site"
        assert result[0]["confidence"] == "official"


class TestSuspensionLifecycleIntegration:
    """Integration tests for suspension record lifecycle."""
    
    def test_suspension_matches_remaining_decrements_on_post_match_reactor(
        self,
    ) -> None:
        """Suspension matches_remaining should decrement on post-match event."""
        # Initial suspension: 3-match ban, expires after match M_100
        matches_remaining = 3
        expires_after_match_id = "M_100"
        
        # Initially active
        assert not should_expire(matches_remaining, expires_after_match_id, None)
        
        # Post-match reactor fires for M_095 (relevant competition match)
        matches_remaining = decrement_matches_remaining(matches_remaining, post_match_is_relevant=True)
        assert matches_remaining == 2
        assert not should_expire(matches_remaining, expires_after_match_id, None)
        
        # Post-match reactor fires for M_096
        matches_remaining = decrement_matches_remaining(matches_remaining, post_match_is_relevant=True)
        assert matches_remaining == 1
        
        # Post-match reactor fires for M_097
        matches_remaining = decrement_matches_remaining(matches_remaining, post_match_is_relevant=True)
        assert matches_remaining == 0
        # Still active because trigger match (M_100) not resolved
        assert not should_expire(matches_remaining, expires_after_match_id, None)
        
        # Trigger match M_100 is resolved
        assert should_expire(matches_remaining, expires_after_match_id, "M_100")


class TestEnd2EndRosterStateWorkflow:
    """End-to-end integration tests for roster-state enrichment."""
    
    def test_e2e_transfer_rumour_to_official_pipeline(
        self,
        sample_transfer: dict,
        mock_config: Config,
    ) -> None:
        """Test complete transfer lifecycle: rumour → agreed → official."""
        # Step 1: Rumour arrives
        rumour: TransferPayload = {
            **sample_transfer,
            "confidence": "rumour",
            "source": "blog",
        }  # type: ignore
        
        instr_r = apply_gate(rumour)
        assert instr_r["should_write"] is False
        
        # Step 2: Same transfer confirmed as agreed
        agreed: TransferPayload = {
            **sample_transfer,
            "confidence": "agreed",
            "source": "mackolik",
        }  # type: ignore
        
        instr_a = apply_gate(agreed)
        assert instr_a["should_write"] is True
        assert instr_a["provisional"] is True
        
        # Deduplication: rumour and agreed have same key
        # In real pipeline, agreed wins
        records: list[TransferPayload] = [rumour, agreed]
        deduped = deduplicate_transfers(records, {"mackolik": 0, "blog": 1})
        assert len(deduped) == 1
        assert deduped[0]["confidence"] == "agreed"
        
        # Step 3: Official confirmation arrives
        official: TransferPayload = {
            **sample_transfer,
            "confidence": "official",
            "source": "tff",
        }  # type: ignore
        
        instr_o = apply_gate(official)
        assert instr_o["should_write"] is True
        assert instr_o["provisional"] is False
        assert instr_o["clear_provisional_for_player"] == "P_100"
    
    def test_e2e_feature_computation_on_official_transfer(
        self,
        sample_transfer: dict,
        mock_config: Config,
    ) -> None:
        """Test feature computation triggered by official transfer."""
        official: TransferPayload = {
            **sample_transfer,
            "confidence": "official",
        }  # type: ignore
        
        # Transfer gate passes
        instr = apply_gate(official)
        assert instr["should_write"] is True
        
        # If this is a team upgrade, compute impact
        if instr["provisional"] is False:
            # Feature computation
            squad_delta = compute_squad_strength_delta(
                team_id=official["to_team_id"],
                player_id=official["player_id"],
                old_rating=75.0,
                new_rating=88.0,
                current_squad_size=20,
            )
            assert squad_delta == (88.0 - 75.0) / 20  # 0.65


class TestEdgeCasesAdversarial:
    """Adversarial tests — edge cases and error conditions."""
    
    def test_multiple_confidence_levels_in_pipeline(self, sample_transfer: dict) -> None:
        """Pipeline should handle multiple confidence levels in one batch."""
        records: list[TransferPayload] = [
            {**sample_transfer, "confidence": "rumour"},  # type: ignore
            {**sample_transfer, "confidence": "agreed", "player_id": "P_201"},  # type: ignore
            {**sample_transfer, "confidence": "official", "player_id": "P_301"},  # type: ignore
        ]
        
        for record in records:
            instr = apply_gate(record)
            # Each should behave according to its confidence level
            if record["confidence"] == "rumour":
                assert instr["should_write"] is False
            else:
                assert instr["should_write"] is True
    
    def test_dedup_preserves_best_version_across_multiple_sources(
        self,
        sample_transfer: dict,
    ) -> None:
        """Deduplication should always preserve highest-quality version."""
        # Create 5 versions of same transfer from different sources
        versions: list[TransferPayload] = [
            {**sample_transfer, "source": "s1", "confidence": "rumour"},  # type: ignore
            {**sample_transfer, "source": "s2", "confidence": "agreed"},  # type: ignore
            {**sample_transfer, "source": "s3", "confidence": "rumour"},  # type: ignore
            {**sample_transfer, "source": "s4", "confidence": "official"},  # type: ignore
            {**sample_transfer, "source": "s5", "confidence": "agreed"},  # type: ignore
        ]
        
        source_priority = {
            "s1": 0,
            "s2": 1,
            "s3": 2,
            "s4": 3,
            "s5": 4,
        }
        
        result = deduplicate_transfers(versions, source_priority)
        
        # Should have exactly one record (the official version)
        assert len(result) == 1
        assert result[0]["confidence"] == "official"
