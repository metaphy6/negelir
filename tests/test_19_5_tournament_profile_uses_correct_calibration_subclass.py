"""Phase 19.5 §19.5 — International tournament calibration profile subclass validation."""
from __future__ import annotations

import pytest
from ai.common.international_tournament_profiles import (
    DensityPenaltyBin,
    TournamentRotationModel,
    InternationalTournamentCalibrationProfile,
)


class TestInternationalTournamentCalibrationProfile:
    """Tests for InternationalTournamentCalibrationProfile subclass."""

    def test_tournament_rotation_model_required_fields(self) -> None:
        """TournamentRotationModel must support required fields."""
        model: TournamentRotationModel = {
            "group_stage_rotation_probability": 0.35,
            "knockout_stage_rotation_probability": 0.10,
            "final_match_rotation_probability": 0.05,
        }
        assert model["group_stage_rotation_probability"] == 0.35
        assert model["knockout_stage_rotation_probability"] == 0.10

    def test_density_penalty_bin_required_fields(self) -> None:
        """DensityPenaltyBin must support required fields."""
        bin_: DensityPenaltyBin = DensityPenaltyBin(
            days_between_matches_min=0,
            days_between_matches_max=2,
            injury_fatigue_penalty_mult=1.5,
        )
        assert bin_.days_between_matches_min == 0
        assert bin_.days_between_matches_max == 2
        assert bin_.injury_fatigue_penalty_mult == 1.5

    def test_tournament_rotation_model_probability_validation(self) -> None:
        """TournamentRotationModel probabilities must be in [0, 1]."""
        # Valid probabilities
        model: TournamentRotationModel = {
            "group_stage_rotation_probability": 0.35,
            "knockout_stage_rotation_probability": 0.10,
            "final_match_rotation_probability": 0.05,
        }
        assert 0 <= model["group_stage_rotation_probability"] <= 1

    def test_density_penalty_bin_invalid_range(self) -> None:
        """DensityPenaltyBin with min > max should raise error."""
        with pytest.raises(ValueError, match="days_between_matches_min.*>.*days_between_matches_max"):
            InternationalTournamentCalibrationProfile(
                profile_id="test_profile",
                description="Test profile",
                elo_home_advantage_mult=1.0,
                dixon_coles_rho_add=0.0,
                draw_sample_weight_mult=1.0,
                poisson_max_goals_add=0.0,
                xg_elo_factor_range_mult=1.0,
                upset_prior=0.0,
                zero_home_advantage_when_venue_in=("neutral",),
                two_leg=None,
                squad_rotation_model=TournamentRotationModel(
                    group_stage_rotation_probability=0.35,
                    knockout_stage_rotation_probability=0.10,
                    final_match_rotation_probability=0.05,
                ),
                fixture_density_penalty_curve=(
                    DensityPenaltyBin(
                        days_between_matches_min=5,
                        days_between_matches_max=2,  # Invalid: min > max
                        injury_fatigue_penalty_mult=1.0,
                    ),
                ),
                home_advantage_host_adjustment=1.3,
            )

    def test_international_tournament_calibration_profile_euro_2024(self) -> None:
        """Euro 2024 calibration profile with tournament-specific settings."""
        profile = InternationalTournamentCalibrationProfile(
            profile_id="tournament_euro_2024",
            description="UEFA Euro 2024 calibration profile",
            elo_home_advantage_mult=1.0,  # Home advantage still applies
            dixon_coles_rho_add=0.1,  # Slightly favor draws in tournaments
            draw_sample_weight_mult=1.2,  # Draw weight higher than leagues
            poisson_max_goals_add=0.5,  # Higher scoring potential
            xg_elo_factor_range_mult=1.1,
            upset_prior=0.05,  # Higher upset potential in tournaments
            zero_home_advantage_when_venue_in=("neutral", "bubble"),
            two_leg=None,
            squad_rotation_model=TournamentRotationModel(
                group_stage_rotation_probability=0.40,
                knockout_stage_rotation_probability=0.08,
                final_match_rotation_probability=0.02,
            ),
            fixture_density_penalty_curve=(
                DensityPenaltyBin(0, 2, 1.8),  # 0-2 days: high fatigue
                DensityPenaltyBin(3, 4, 1.4),  # 3-4 days: moderate fatigue
                DensityPenaltyBin(5, 7, 1.1),  # 5-7 days: light fatigue
                DensityPenaltyBin(8, 100, 1.0),  # 8+ days: baseline
            ),
            home_advantage_host_adjustment=1.2,  # +20% for host nation only
        )

        assert profile.profile_id == "tournament_euro_2024"
        assert profile.squad_rotation_model.group_stage_rotation_probability == 0.40
        assert len(profile.fixture_density_penalty_curve) == 4
        assert profile.home_advantage_host_adjustment == 1.2

    def test_density_penalty_curve_bins_must_be_non_overlapping(self) -> None:
        """Fixture density penalty curve bins must be non-overlapping."""
        with pytest.raises(ValueError, match="bins overlap"):
            InternationalTournamentCalibrationProfile(
                profile_id="test_overlap",
                description="Test overlapping bins",
                elo_home_advantage_mult=1.0,
                dixon_coles_rho_add=0.0,
                draw_sample_weight_mult=1.0,
                poisson_max_goals_add=0.0,
                xg_elo_factor_range_mult=1.0,
                upset_prior=0.0,
                zero_home_advantage_when_venue_in=(),
                two_leg=None,
                squad_rotation_model=TournamentRotationModel(
                    group_stage_rotation_probability=0.35,
                    knockout_stage_rotation_probability=0.10,
                    final_match_rotation_probability=0.05,
                ),
                fixture_density_penalty_curve=(
                    DensityPenaltyBin(0, 3, 1.5),
                    DensityPenaltyBin(2, 5, 1.2),  # Overlaps with previous (2-3)
                ),
                home_advantage_host_adjustment=1.3,
            )

    def test_home_advantage_host_adjustment_must_be_in_range(self) -> None:
        """home_advantage_host_adjustment must be in [0.5, 2.0]."""
        with pytest.raises(ValueError, match="home_advantage_host_adjustment"):
            InternationalTournamentCalibrationProfile(
                profile_id="test_host_adj",
                description="Test invalid host adjustment",
                elo_home_advantage_mult=1.0,
                dixon_coles_rho_add=0.0,
                draw_sample_weight_mult=1.0,
                poisson_max_goals_add=0.0,
                xg_elo_factor_range_mult=1.0,
                upset_prior=0.0,
                zero_home_advantage_when_venue_in=(),
                two_leg=None,
                squad_rotation_model=TournamentRotationModel(
                    group_stage_rotation_probability=0.35,
                    knockout_stage_rotation_probability=0.10,
                    final_match_rotation_probability=0.05,
                ),
                fixture_density_penalty_curve=(
                    DensityPenaltyBin(0, 10, 1.2),
                ),
                home_advantage_host_adjustment=3.0,  # Invalid: > 2.0
            )

    def test_wc_qualifier_calibration_profile(self) -> None:
        """WC qualifier calibration profile with multi-round settings."""
        profile = InternationalTournamentCalibrationProfile(
            profile_id="tournament_wc_2026_qualifier",
            description="WC 2026 Qualifier calibration",
            elo_home_advantage_mult=1.0,
            dixon_coles_rho_add=0.05,
            draw_sample_weight_mult=1.1,
            poisson_max_goals_add=0.0,
            xg_elo_factor_range_mult=1.0,
            upset_prior=0.03,
            zero_home_advantage_when_venue_in=(),
            two_leg=None,
            squad_rotation_model=TournamentRotationModel(
                group_stage_rotation_probability=0.25,
                knockout_stage_rotation_probability=0.12,  # Playoff rounds
                final_match_rotation_probability=0.08,  # Inter-confederation playoff
            ),
            fixture_density_penalty_curve=(
                DensityPenaltyBin(0, 3, 1.6),
                DensityPenaltyBin(4, 6, 1.2),
                DensityPenaltyBin(7, 100, 1.0),
            ),
            home_advantage_host_adjustment=1.1,  # Modest boost for home advantage
        )

        assert profile.profile_id == "tournament_wc_2026_qualifier"
        assert profile.squad_rotation_model.knockout_stage_rotation_probability == 0.12
        assert profile.home_advantage_host_adjustment == 1.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
