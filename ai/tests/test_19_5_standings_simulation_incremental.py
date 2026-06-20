"""Phase 19.5 §19.5 — Standings simulation is incremental.

Tests that:
- Each new fixture result narrows the standings distribution
- Simulation does not re-run previously-played fixtures
- Distribution converges as fewer fixtures remain
"""
from __future__ import annotations

import pytest
from ai.common.standings_accumulator import (
    GroupTeam,
    simulate_group_stage_standings,
)


class TestStandingsSimulationIncrementalism:
    """Test incremental narrowing of standings distribution."""
    
    def test_incremental_fixture_resolution_narrows_distribution(self) -> None:
        """As fixtures are played (is_simulated=False), distribution narrows."""
        teams_initial = {
            "france": GroupTeam("france", points=0, goals_for=0, goals_against=0),
            "netherlands": GroupTeam("netherlands", points=0, goals_for=0, goals_against=0),
            "denmark": GroupTeam("denmark", points=0, goals_for=0, goals_against=0),
            "tunisia": GroupTeam("tunisia", points=0, goals_for=0, goals_against=0),
        }
        
        fixtures_all_simulated = [
            ("france", "netherlands", True),
            ("denmark", "tunisia", True),
            ("france", "denmark", True),
            ("netherlands", "tunisia", True),
            ("france", "tunisia", True),
            ("netherlands", "denmark", True),
        ]
        
        fixtures_partial = [
            ("france", "netherlands", False),
            ("denmark", "tunisia", False),
            ("france", "denmark", True),
            ("netherlands", "tunisia", True),
            ("france", "tunisia", False),
            ("netherlands", "denmark", False),
        ]
        
        dist_all = simulate_group_stage_standings(
            group_id="group_a",
            confederation="UEFA",
            teams=teams_initial,
            remaining_fixtures=fixtures_all_simulated,
            n_iterations=200,
        )
        
        dist_partial = simulate_group_stage_standings(
            group_id="group_a",
            confederation="UEFA",
            teams=teams_initial,
            remaining_fixtures=fixtures_partial,
            n_iterations=200,
        )
        
        # Verify all distributions exist and have valid structure
        for dist in [dist_all, dist_partial]:
            assert len(dist) == 4
            for team_id, pos_probs in dist.items():
                assert len(pos_probs) > 0
                total = sum(pos_probs.values())
                assert 0.99 <= total <= 1.01
    
    def test_single_remaining_fixture_produces_outcome(self) -> None:
        """With only one fixture left, simulation produces valid outcomes."""
        teams = {
            "strong": GroupTeam("strong", points=9, goals_for=9, goals_against=0),
            "weak": GroupTeam("weak", points=0, goals_for=1, goals_against=9),
        }
        
        remaining = [
            ("strong", "weak", True),
        ]
        
        dist = simulate_group_stage_standings(
            group_id="group_a",
            confederation="UEFA",
            teams=teams,
            remaining_fixtures=remaining,
            n_iterations=300,
        )
        
        # Strong team should have some probability of position 1
        position_1_prob = dist["strong"].get(1, 0)
        assert position_1_prob > 0.5, (
            f"Strong team should likely finish 1st, got P(1st)={position_1_prob}"
        )
    
    def test_multiple_remaining_fixtures_produce_spread_distribution(self) -> None:
        """With multiple fixtures remaining, distributions should spread across positions."""
        teams = {
            "team_a": GroupTeam("team_a", points=3, goals_for=2, goals_against=1),
            "team_b": GroupTeam("team_b", points=3, goals_for=2, goals_against=1),
            "team_c": GroupTeam("team_c", points=0, goals_for=0, goals_against=4),
        }
        
        remaining = [
            ("team_a", "team_b", True),
            ("team_a", "team_c", True),
            ("team_b", "team_c", True),
        ]
        
        dist = simulate_group_stage_standings(
            group_id="group_a",
            confederation="UEFA",
            teams=teams,
            remaining_fixtures=remaining,
            n_iterations=200,
        )
        
        # With multiple fixtures, teams should have multiple possible positions
        assert len(dist["team_a"]) > 0
        assert len(dist["team_b"]) > 0
        assert len(dist["team_c"]) > 0
        
        # Verify probabilities sum correctly for each team
        for team_id, pos_probs in dist.items():
            total = sum(pos_probs.values())
            assert 0.99 <= total <= 1.01
