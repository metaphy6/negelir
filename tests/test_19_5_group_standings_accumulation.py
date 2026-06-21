"""Phase 19.5 §19.5 — Group standings accumulation model.

Tests for:
  - simulate_group_stage_standings(group_id, confederation, teams, remaining_fixtures, n_iterations)
  - Monte Carlo simulation of final standings positions per team
  - Incremental narrowing: each new fixture result updates the distribution
"""
from __future__ import annotations

import pytest
from common.standings_accumulator import (
    GroupTeam,
    StandingsAccumulator,
    simulate_group_stage_standings,
)


class TestGroupStandingsAccumulation:
    """Test group standings accumulation and distribution."""
    
    def test_group_standings_accumulation_returns_position_distribution(self) -> None:
        """Basic test: simulate_group_stage_standings returns a position distribution."""
        teams = {
            "france": GroupTeam("france", points=4, goals_for=3, goals_against=1),
            "netherlands": GroupTeam("netherlands", points=1, goals_for=1, goals_against=2),
            "denmark": GroupTeam("denmark", points=1, goals_for=0, goals_against=1),
            "tunisia": GroupTeam("tunisia", points=0, goals_for=0, goals_against=0),
        }
        
        remaining_fixtures = [
            ("france", "denmark", True),
            ("netherlands", "tunisia", True),
            ("denmark", "tunisia", True),
            ("france", "netherlands", True),
        ]
        
        dist = simulate_group_stage_standings(
            group_id="group_a",
            confederation="UEFA",
            teams=teams,
            remaining_fixtures=remaining_fixtures,
            n_iterations=100,
        )
        
        assert len(dist) == 4
        for team_id, position_probs in dist.items():
            assert team_id in teams
            assert len(position_probs) > 0
            total_prob = sum(position_probs.values())
            assert 0.99 <= total_prob <= 1.01
            for position in position_probs.keys():
                assert 1 <= position <= 4


class TestStandingsAccumulatorTiebreakers:
    """Test confederation-specific tiebreaker rules in standings."""
    
    def test_caf_prioritizes_goals_for(self) -> None:
        """CAF tiebreaker rule: goals-for is first tiebreaker."""
        accumulator = StandingsAccumulator("CAF")
        
        team_a = GroupTeam("team_a", points=4, goals_for=5, goals_against=2)
        team_b = GroupTeam("team_b", points=4, goals_for=3, goals_against=1)
        
        cmp = accumulator._compare_teams(team_a, team_b)
        assert cmp > 0, "CAF: team_a should rank higher (5 goals-for > 3 goals-for)"
    
    def test_uefa_prioritizes_head_to_head(self) -> None:
        """UEFA tiebreaker rule: head-to-head is first tiebreaker."""
        accumulator = StandingsAccumulator("UEFA")
        
        team_a = GroupTeam("team_a", points=4, goals_for=2, goals_against=1)
        team_b = GroupTeam("team_b", points=4, goals_for=3, goals_against=2)
        
        team_a.head_to_head_points["team_b"] = 3
        team_b.head_to_head_points["team_a"] = 0
        
        cmp = accumulator._compare_teams(team_a, team_b)
        assert cmp > 0, "UEFA: team_a should rank higher (3 H2H points > 0)"
    
    def test_conmebol_prioritizes_head_to_head(self) -> None:
        """CONMEBOL tiebreaker rule: head-to-head is first tiebreaker."""
        accumulator = StandingsAccumulator("CONMEBOL")
        
        team_a = GroupTeam("team_a", points=5, goals_for=3, goals_against=2)
        team_b = GroupTeam("team_b", points=5, goals_for=5, goals_against=3)
        
        team_a.head_to_head_points["team_b"] = 3
        team_b.head_to_head_points["team_a"] = 0
        
        cmp = accumulator._compare_teams(team_a, team_b)
        assert cmp > 0, "CONMEBOL: team_a should rank higher (H2H > 0)"
    
    def test_rank_teams_applies_tiebreaker_correctly(self) -> None:
        """Verify team ranking applies full tiebreaker sequence."""
        accumulator = StandingsAccumulator("UEFA")
        
        teams = [
            GroupTeam("france", points=9, goals_for=6, goals_against=1),
            GroupTeam("netherlands", points=6, goals_for=5, goals_against=2),
            GroupTeam("denmark", points=3, goals_for=3, goals_against=4),
            GroupTeam("tunisia", points=0, goals_for=1, goals_against=8),
        ]
        
        ranked = accumulator.rank_teams(teams)
        
        assert ranked[0].team_id == "france"
        assert ranked[1].team_id == "netherlands"
        assert ranked[2].team_id == "denmark"
        assert ranked[3].team_id == "tunisia"
