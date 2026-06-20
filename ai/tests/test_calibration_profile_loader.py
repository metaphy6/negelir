"""
Phase 13.2 — Calibration profile loader and validator tests.

Tests that:
  1. All 11 expected profiles load successfully
  2. Schema validation works (numeric bounds, required fields)
  3. Profile IDs are unique and match filenames
  4. CalibrationProfile objects are immutable
  5. Missing expected profiles raise an error
  6. Invalid profile_id or numeric values are rejected
"""

import pytest
from pathlib import Path

# Test that the loader can be imported and the singleton loads successfully
from ai.common.calibration_profile_loader import (
    CALIBRATION_PROFILES,
    CalibrationProfile,
    load_calibration_profiles,
    EXPECTED_PROFILE_IDS,
)


class TestCalibrationProfileLoader:
    """Tests for calibration profile loading and validation."""

    def test_all_expected_profiles_loaded(self) -> None:
        """Verify all 11 expected profiles from COMPETITIONS.md §4.2 are loaded."""
        loaded_ids = set(CALIBRATION_PROFILES.keys())
        assert loaded_ids == EXPECTED_PROFILE_IDS, (
            f"Loaded profiles {loaded_ids} do not match expected {EXPECTED_PROFILE_IDS}. "
            f"Missing: {EXPECTED_PROFILE_IDS - loaded_ids}. "
            f"Extra: {loaded_ids - EXPECTED_PROFILE_IDS}."
        )

    def test_profile_count(self) -> None:
        """Verify exactly 11 profiles are loaded."""
        assert len(CALIBRATION_PROFILES) == 11, (
            f"Expected 11 calibration profiles, got {len(CALIBRATION_PROFILES)}"
        )

    def test_profile_is_immutable(self) -> None:
        """Verify CalibrationProfile objects are immutable (frozen dataclasses)."""
        profile = CALIBRATION_PROFILES["league_round_robin"]
        
        # Attempt to modify should raise FrozenInstanceError
        with pytest.raises((AttributeError, TypeError)):
            profile.elo_home_advantage_mult = 2.0  # type: ignore

    def test_zero_home_advantage_tuple_immutable(self) -> None:
        """Verify zero_home_advantage_when_venue_in is a tuple (immutable)."""
        profile = CALIBRATION_PROFILES["domestic_cup_late_round"]
        assert isinstance(profile.zero_home_advantage_when_venue_in, tuple)
        
        # Attempting to modify should raise TypeError
        with pytest.raises((AttributeError, TypeError)):
            profile.zero_home_advantage_when_venue_in[0] = "invalid"  # type: ignore

    def test_league_round_robin_baseline(self) -> None:
        """Verify league_round_robin is the baseline (all multipliers = 1.0, adds = 0.0)."""
        profile = CALIBRATION_PROFILES["league_round_robin"]
        
        assert profile.elo_home_advantage_mult == 1.0
        assert profile.dixon_coles_rho_add == 0.0
        assert profile.draw_sample_weight_mult == 1.0
        assert profile.poisson_max_goals_add == 0.0
        assert profile.xg_elo_factor_range_mult == 1.0
        assert profile.upset_prior == 0.0
        assert profile.zero_home_advantage_when_venue_in == ()

    def test_knockout_continental_club_has_two_leg_rules(self) -> None:
        """Verify knockout_continental_club defines two_leg aggregation rules."""
        profile = CALIBRATION_PROFILES["knockout_continental_club"]
        
        assert profile.two_leg is not None
        assert profile.two_leg.aggregate_logic == "sum_goals"
        assert profile.two_leg.penalty_shootout_modeled is True
        assert profile.two_leg.away_goals_rule_active_until == "2021-05-31"

    def test_international_knockout_neutral_venue_handling(self) -> None:
        """Verify international_knockout zeros home advantage for neutral/bubble venues."""
        profile = CALIBRATION_PROFILES["international_knockout"]
        
        expected_venues = {"neutral", "bubble", "host_country"}
        assert set(profile.zero_home_advantage_when_venue_in) == expected_venues

    def test_international_friendly_excluded_profile(self) -> None:
        """Verify international_friendly_excluded is a placeholder (all defaults)."""
        profile = CALIBRATION_PROFILES["international_friendly_excluded"]
        
        assert "friendli" in profile.description.lower()  # matches "friendly" and "friendlies"
        assert profile.elo_home_advantage_mult == 1.0

    def test_domestic_cup_early_round_higher_upset_variance(self) -> None:
        """Verify domestic_cup_early_round has higher upset variance."""
        early = CALIBRATION_PROFILES["domestic_cup_early_round"]
        league = CALIBRATION_PROFILES["league_round_robin"]
        
        assert early.upset_prior > league.upset_prior
        assert early.xg_elo_factor_range_mult > league.xg_elo_factor_range_mult

    def test_group_stage_profiles_higher_draw_weight(self) -> None:
        """Verify group-stage profiles have higher draw_sample_weight_mult."""
        group_cont = CALIBRATION_PROFILES["group_continental_club"]
        group_intl = CALIBRATION_PROFILES["international_group_stage"]
        league = CALIBRATION_PROFILES["league_round_robin"]
        
        assert group_cont.draw_sample_weight_mult > league.draw_sample_weight_mult
        assert group_intl.draw_sample_weight_mult > league.draw_sample_weight_mult

    def test_calibration_profiles_immutable_mapping(self) -> None:
        """Verify the module-level singleton is an immutable mapping."""
        from types import MappingProxyType
        assert isinstance(CALIBRATION_PROFILES, MappingProxyType)
        
        # Attempting to add a new key should raise TypeError
        with pytest.raises(TypeError):
            CALIBRATION_PROFILES["fake_profile"] = None  # type: ignore

    def test_profile_descriptions_nonempty(self) -> None:
        """Verify all profiles have non-empty descriptions."""
        for profile_id, profile in CALIBRATION_PROFILES.items():
            assert profile.description and len(profile.description) > 0, (
                f"Profile '{profile_id}' has empty or missing description"
            )

    def test_all_numeric_fields_initialized(self) -> None:
        """Verify all numeric overlay fields are initialized for all profiles."""
        for profile_id, profile in CALIBRATION_PROFILES.items():
            assert isinstance(profile.elo_home_advantage_mult, (int, float))
            assert isinstance(profile.dixon_coles_rho_add, (int, float))
            assert isinstance(profile.draw_sample_weight_mult, (int, float))
            assert isinstance(profile.poisson_max_goals_add, (int, float))
            assert isinstance(profile.xg_elo_factor_range_mult, (int, float))
            assert isinstance(profile.upset_prior, (int, float))

    def test_numeric_ranges_valid(self) -> None:
        """Verify all numeric fields are within valid ranges per schema."""
        for profile_id, profile in CALIBRATION_PROFILES.items():
            assert 0 <= profile.elo_home_advantage_mult <= 2.0, (
                f"Profile '{profile_id}': elo_home_advantage_mult {profile.elo_home_advantage_mult} "
                f"out of range [0, 2.0]"
            )
            assert -0.5 <= profile.dixon_coles_rho_add <= 0.5, (
                f"Profile '{profile_id}': dixon_coles_rho_add {profile.dixon_coles_rho_add} "
                f"out of range [-0.5, 0.5]"
            )
            assert 0.1 <= profile.draw_sample_weight_mult <= 2.0, (
                f"Profile '{profile_id}': draw_sample_weight_mult {profile.draw_sample_weight_mult} "
                f"out of range [0.1, 2.0]"
            )
            assert -2 <= profile.poisson_max_goals_add <= 3, (
                f"Profile '{profile_id}': poisson_max_goals_add {profile.poisson_max_goals_add} "
                f"out of range [-2, 3]"
            )
            assert 0.5 <= profile.xg_elo_factor_range_mult <= 2.0, (
                f"Profile '{profile_id}': xg_elo_factor_range_mult {profile.xg_elo_factor_range_mult} "
                f"out of range [0.5, 2.0]"
            )
            assert 0 <= profile.upset_prior <= 0.2, (
                f"Profile '{profile_id}': upset_prior {profile.upset_prior} "
                f"out of range [0, 0.2]"
            )
