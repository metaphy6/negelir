"""Phase 21.1 §21.1 — Enrichment features tests.

Tests for squad_strength_delta, cohesion_penalty, departure_shock:
  - Correct delta computation on transfers
  - Cohesion penalty decays over 4 appearances
  - Departure shock triggered within 14d for top-quartile
  - Edge cases: null ratings, empty squads, missing config
  - Time boundaries: exactly 14d, 15d, 0d

Per ROADMAP §21.1 bullet 5 and ENRICHMENT_DATA.md §2.3.
Minimum 8 tests including ≥ 2 adversarial.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from model.enrichment_features import (
    compute_squad_strength_delta,
    compute_cohesion_penalty,
    compute_departure_shock,
)
from ai.common.config import Config


@pytest.fixture
def mock_config() -> Config:
    """Config with enrichment settings."""
    cfg = Config()
    cfg.enrichment_cohesion_penalty_curve = [0.15, 0.10, 0.05, 0.02]
    cfg.enrichment_departure_shock = 0.05
    return cfg


class TestSquadStrengthDelta:
    """Tests for squad strength change computation."""
    
    def test_positive_delta_on_upgrade(self) -> None:
        """Signing a higher-rated player should increase squad strength."""
        delta = compute_squad_strength_delta(
            team_id="T_001",
            player_id="P_100",
            old_rating=75.0,
            new_rating=82.0,
            current_squad_size=20,
        )
        assert delta > 0.0
        assert delta == (82.0 - 75.0) / 20  # 0.35
    
    def test_negative_delta_on_downgrade(self) -> None:
        """Selling a high-rated player should decrease squad strength."""
        delta = compute_squad_strength_delta(
            team_id="T_001",
            player_id="P_100",
            old_rating=82.0,
            new_rating=70.0,
            current_squad_size=20,
        )
        assert delta < 0.0
        assert delta == (70.0 - 82.0) / 20  # -0.60
    
    def test_zero_delta_on_no_rating_change(self) -> None:
        """Same rating should produce zero delta."""
        delta = compute_squad_strength_delta(
            team_id="T_001",
            player_id="P_100",
            old_rating=75.0,
            new_rating=75.0,
            current_squad_size=20,
        )
        assert delta == 0.0


class TestCohesionPenalty:
    """Tests for cohesion penalty over appearances."""
    
    def test_appearance_0_has_maximum_penalty(self, mock_config: Config) -> None:
        """Player before first appearance gets full penalty."""
        penalty = compute_cohesion_penalty(0, mock_config)
        assert penalty == -0.15
    
    def test_appearance_1_has_medium_penalty(self, mock_config: Config) -> None:
        """Player after 1 appearance gets reduced penalty."""
        penalty = compute_cohesion_penalty(1, mock_config)
        assert penalty == -0.10
    
    def test_appearance_2_has_low_penalty(self, mock_config: Config) -> None:
        """Player after 2 appearances gets further reduced penalty."""
        penalty = compute_cohesion_penalty(2, mock_config)
        assert penalty == -0.05
    
    def test_appearance_3_has_minimal_penalty(self, mock_config: Config) -> None:
        """Player after 3 appearances gets minimal penalty."""
        penalty = compute_cohesion_penalty(3, mock_config)
        assert penalty == -0.02
    
    def test_appearance_4_plus_no_penalty(self, mock_config: Config) -> None:
        """Player after 4+ appearances has no penalty."""
        penalty = compute_cohesion_penalty(4, mock_config)
        assert penalty == 0.0
        
        # Also test higher appearance counts
        penalty_high = compute_cohesion_penalty(10, mock_config)
        assert penalty_high == 0.0
    
    def test_penalty_curve_configurable(self) -> None:
        """Penalty curve should be configurable via config."""
        cfg = Config()
        cfg.enrichment_cohesion_penalty_curve = [0.20, 0.15, 0.10, 0.05]
        
        penalty_0 = compute_cohesion_penalty(0, cfg)
        penalty_1 = compute_cohesion_penalty(1, cfg)
        
        assert penalty_0 == -0.20
        assert penalty_1 == -0.15


class TestDepartureShock:
    """Tests for departure shock when top-quartile player leaves."""
    
    def test_no_shock_if_not_top_quartile(self, mock_config: Config) -> None:
        """Player below top quartile should not trigger shock."""
        shock = compute_departure_shock(
            departure_date_utc="2026-06-20T00:00:00Z",
            player_rating=70.0,  # Below quartile threshold
            squad_ratings=[90.0, 85.0, 80.0, 75.0, 70.0, 65.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",
        )
        assert shock == 0.0
    
    def test_shock_if_top_quartile_within_14d(self, mock_config: Config) -> None:
        """Top-quartile player departing within 14d should trigger shock."""
        shock = compute_departure_shock(
            departure_date_utc="2026-06-20T00:00:00Z",
            player_rating=88.0,  # In top quartile
            squad_ratings=[90.0, 88.0, 85.0, 82.0, 75.0, 70.0, 65.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",
        )
        assert shock < 0.0
        assert shock == -mock_config.enrichment_departure_shock
    
    def test_no_shock_at_14d_boundary(self, mock_config: Config) -> None:
        """Shock expires at 14d mark."""
        shock = compute_departure_shock(
            departure_date_utc="2026-06-07T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[90.0, 88.0, 85.0, 82.0, 75.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",  # Exactly 14 days later
        )
        assert shock == 0.0
    
    def test_shock_within_13d(self, mock_config: Config) -> None:
        """Shock applies within 13d window."""
        shock = compute_departure_shock(
            departure_date_utc="2026-06-08T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[90.0, 88.0, 85.0, 82.0, 75.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",  # 13 days later
        )
        assert shock < 0.0


class TestDepartureShockEdgeCases:
    """Adversarial tests — edge cases and error conditions."""
    
    def test_no_shock_if_departure_in_future(self, mock_config: Config) -> None:
        """Future departure should not trigger shock."""
        shock = compute_departure_shock(
            departure_date_utc="2026-07-01T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[90.0, 88.0, 85.0, 82.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",
        )
        assert shock == 0.0
    
    def test_no_shock_if_rating_missing(self, mock_config: Config) -> None:
        """Missing player rating should not trigger shock."""
        shock = compute_departure_shock(
            departure_date_utc="2026-06-10T00:00:00Z",
            player_rating=None,
            squad_ratings=[90.0, 88.0, 85.0, 82.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",
        )
        assert shock == 0.0
    
    def test_no_shock_if_squad_ratings_empty(self, mock_config: Config) -> None:
        """Empty squad should not trigger shock."""
        shock = compute_departure_shock(
            departure_date_utc="2026-06-10T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",
        )
        assert shock == 0.0
    
    def test_shock_uses_correct_coefficient(self, mock_config: Config) -> None:
        """Shock magnitude should match config coefficient."""
        mock_config.enrichment_departure_shock = 0.10  # Custom coefficient
        
        shock = compute_departure_shock(
            departure_date_utc="2026-06-10T00:00:00Z",
            player_rating=88.0,
            squad_ratings=[90.0, 88.0, 85.0, 82.0],
            cfg=mock_config,
            current_date_utc="2026-06-21T00:00:00Z",
        )
        assert shock == -0.10
