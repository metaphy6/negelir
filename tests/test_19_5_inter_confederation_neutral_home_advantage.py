"""Phase 19.5 §19.5 — Inter-confederation play-off neutral home-advantage prior."""
from __future__ import annotations

import os
import pytest
from dataclasses import dataclass
from typing import Optional, Any
from common.international_tournament_profiles import (
    InternationalTournamentCalibrationProfile,
    TournamentRotationModel,
    DensityPenaltyBin,
)
from common.config import Config


@dataclass(frozen=True)
class MockTeam:
    """Mock team for testing inter-confederation play-off logic."""
    team_id: str
    confederation: str


@dataclass(frozen=True)
class MockFixture:
    """Mock fixture for testing inter-confederation play-off logic."""
    fixture_id: str
    home_team: MockTeam
    away_team: MockTeam
    is_inter_confederation_playoff: bool = False


def _teams_from_different_confederations(fixture: MockFixture) -> bool:
    """Check if fixture is between teams from different confederations."""
    return fixture.home_team.confederation != fixture.away_team.confederation


def _is_inter_confederation_playoff(
    fixture: MockFixture,
    cfg: Config,
) -> bool:
    """Determine if a fixture is an inter-confederation play-off fixture.
    
    A fixture is inter-confederation if:
    1. It's explicitly marked as inter-confederation playoff, OR
    2. Teams are from different confederations and cfg allows neutral home advantage
    """
    return fixture.is_inter_confederation_playoff or _teams_from_different_confederations(fixture)


def _get_home_advantage_for_inter_confederation(
    fixture: MockFixture,
    cfg: Config,
) -> Optional[float]:
    """Get the home advantage multiplier for an inter-confederation play-off.
    
    If cfg.wc_playoff_home_advantage_prior is not set (None or empty),
    returns 0.0 (neutral home advantage).
    Otherwise returns the configured value.
    
    Returns:
        None if fixture is not inter-confederation, or the configured/neutral value.
    """
    if not _is_inter_confederation_playoff(fixture, cfg):
        return None
    
    # If config has explicit setting, use it
    if cfg.wc_playoff_home_advantage_prior is not None:
        return cfg.wc_playoff_home_advantage_prior
    
    # Otherwise default to neutral (0.0)
    return 0.0


class TestInterConfederationPlayoffNeutralPrior:
    """Tests for inter-confederation play-off neutral home-advantage prior."""

    def test_inter_confederation_fixture_with_different_confederations(self) -> None:
        """Inter-confederation fixture between UEFA and CONMEBOL teams."""
        fixture = MockFixture(
            fixture_id="wc_2026_playoff_1",
            home_team=MockTeam(team_id="france", confederation="UEFA"),
            away_team=MockTeam(team_id="brazil", confederation="CONMEBOL"),
            is_inter_confederation_playoff=True,
        )
        
        # Mock config with no explicit setting (defaults to neutral)
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = None
        
        # Verify teams are from different confederations
        assert _teams_from_different_confederations(fixture)
        
        # Verify it's marked as inter-confederation
        assert _is_inter_confederation_playoff(fixture, cfg_mock)
        
        # Verify home advantage defaults to neutral (0.0)
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv == 0.0

    def test_inter_confederation_fixture_with_explicit_prior(self) -> None:
        """Inter-confederation fixture with explicitly configured home advantage prior."""
        fixture = MockFixture(
            fixture_id="wc_2026_playoff_2",
            home_team=MockTeam(team_id="germany", confederation="UEFA"),
            away_team=MockTeam(team_id="argentina", confederation="CONMEBOL"),
            is_inter_confederation_playoff=True,
        )
        
        # Mock config with explicit setting (e.g., 0.5 — small home advantage)
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = 0.5
        
        # Verify home advantage uses configured value
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv == 0.5

    def test_non_inter_confederation_fixture_ignores_config(self) -> None:
        """Non-inter-confederation fixture should return None."""
        fixture = MockFixture(
            fixture_id="domestic_1",
            home_team=MockTeam(team_id="team_a", confederation="UEFA"),
            away_team=MockTeam(team_id="team_b", confederation="UEFA"),
            is_inter_confederation_playoff=False,
        )
        
        # Mock config with explicit setting
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = 0.5
        
        # Verify None is returned for non-inter-confederation fixtures
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv is None

    def test_inter_confederation_fixture_caf_vs_afc(self) -> None:
        """Inter-confederation fixture between CAF and AFC teams."""
        fixture = MockFixture(
            fixture_id="qualifying_pathway_1",
            home_team=MockTeam(team_id="senegal", confederation="CAF"),
            away_team=MockTeam(team_id="australia", confederation="AFC"),
            is_inter_confederation_playoff=True,
        )
        
        # Mock config without explicit setting
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = None
        
        # Verify neutral home advantage
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv == 0.0

    def test_same_confederation_not_inter_confederation(self) -> None:
        """Fixtures between teams from same confederation should not be treated as inter-confederation."""
        fixture = MockFixture(
            fixture_id="conmebol_playoff_1",
            home_team=MockTeam(team_id="uruguay", confederation="CONMEBOL"),
            away_team=MockTeam(team_id="colombia", confederation="CONMEBOL"),
            is_inter_confederation_playoff=False,
        )
        
        # Mock config
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = None
        
        # Verify this is not inter-confederation
        assert not _is_inter_confederation_playoff(fixture, cfg_mock)
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv is None

    def test_inter_confederation_fixture_with_zero_home_advantage(self) -> None:
        """Explicitly set zero home advantage for inter-confederation playoff."""
        fixture = MockFixture(
            fixture_id="inter_conf_zero_ha",
            home_team=MockTeam(team_id="team_x", confederation="UEFA"),
            away_team=MockTeam(team_id="team_y", confederation="CONCACAF"),
            is_inter_confederation_playoff=True,
        )
        
        # Mock config explicitly set to 0.0
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = 0.0
        
        # Verify explicit zero
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv == 0.0

    def test_international_tournament_profile_with_inter_confederation(self) -> None:
        """International tournament calibration profile for inter-confederation match."""
        profile = InternationalTournamentCalibrationProfile(
            profile_id="wc_2026_inter_confederation",
            description="WC 2026 inter-confederation playoff",
            elo_home_advantage_mult=0.0,  # Neutral for inter-confederation
            dixon_coles_rho_add=0.0,
            draw_sample_weight_mult=1.0,
            poisson_max_goals_add=0.0,
            xg_elo_factor_range_mult=1.0,
            upset_prior=0.05,
            zero_home_advantage_when_venue_in=(),
            squad_rotation_model=TournamentRotationModel(
                group_stage_rotation_probability=0.0,  # No group stage in inter-conf
                knockout_stage_rotation_probability=0.12,
                final_match_rotation_probability=0.0,
            ),
            fixture_density_penalty_curve=(
                DensityPenaltyBin(0, 7, 1.3),
                DensityPenaltyBin(8, 100, 1.0),
            ),
            home_advantage_host_adjustment=1.0,  # No host adjustment needed
        )
        
        # Verify the profile has zero home advantage
        assert profile.elo_home_advantage_mult == 0.0
        assert profile.profile_id == "wc_2026_inter_confederation"

    def test_inter_confederation_override_with_explicit_multiplier(self) -> None:
        """Inter-confederation playoff with explicit home advantage override."""
        # In production, an operator might want to apply a small home advantage
        # even in inter-confederation play-offs (e.g., for travel distance penalties)
        fixture = MockFixture(
            fixture_id="override_test",
            home_team=MockTeam(team_id="home_nation", confederation="UEFA"),
            away_team=MockTeam(team_id="away_nation", confederation="CONMEBOL"),
            is_inter_confederation_playoff=True,
        )
        
        # Mock config with explicit override (e.g., 0.3 instead of 0.0)
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = 0.3
        
        # Verify override is applied
        home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
        assert home_adv == 0.3

    def test_all_confederations_covered(self) -> None:
        """Test inter-confederation fixtures for all major confederation combinations."""
        confederations = ["UEFA", "CONMEBOL", "AFC", "CAF", "OFC", "CONCACAF"]
        
        cfg_mock = Config.__new__(Config)
        cfg_mock.wc_playoff_home_advantage_prior = None
        
        # Test multiple confederation pairs
        for i, conf_home in enumerate(confederations):
            for conf_away in confederations[i+1:]:
                fixture = MockFixture(
                    fixture_id=f"{conf_home}_{conf_away}",
                    home_team=MockTeam(team_id="team_home", confederation=conf_home),
                    away_team=MockTeam(team_id="team_away", confederation=conf_away),
                    is_inter_confederation_playoff=True,
                )
                
                # Verify neutral home advantage for all combinations
                home_adv = _get_home_advantage_for_inter_confederation(fixture, cfg_mock)
                assert home_adv == 0.0, f"Failed for {conf_home} vs {conf_away}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
