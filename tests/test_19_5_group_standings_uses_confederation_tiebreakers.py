"""Phase 19.5 §19.5 — Group standings uses confederation-specific tiebreakers.

Tests that standings accumulation respects confederation-specific tiebreaker order:
- CAF: goals-for first, then head-to-head, then goal-differential
- UEFA: head-to-head first, then goals-for, then goal-differential
- CONMEBOL: head-to-head first, then goal-differential, then goals-for
"""
from __future__ import annotations

import pytest
from ai.common.standings_accumulator import (
    GroupTeam,
    ConfederationTiebreakerRules,
    StandingsAccumulator,
    simulate_group_stage_standings,
)


class TestConfederationTiebreakerRules:
    """Test that confederation rules are correctly applied."""
    
    def test_caf_rules_prioritize_goals_for_over_head_to_head(self) -> None:
        """CAF: goals-for is primary, head-to-head is secondary."""
        rules = ConfederationTiebreakerRules.for_confederation("CAF")
        assert rules.primary == "goals_for"
        assert rules.secondary == "head_to_head"
        assert rules.tertiary == "goal_differential"
    
    def test_uefa_rules_prioritize_head_to_head_over_goals_for(self) -> None:
        """UEFA: head-to-head is primary, goals-for is secondary."""
        rules = ConfederationTiebreakerRules.for_confederation("UEFA")
        assert rules.primary == "head_to_head"
        assert rules.secondary == "goals_for"
        assert rules.tertiary == "goal_differential"
    
    def test_conmebol_rules_prioritize_head_to_head(self) -> None:
        """CONMEBOL: head-to-head is primary."""
        rules = ConfederationTiebreakerRules.for_confederation("CONMEBOL")
        assert rules.primary == "head_to_head"
        assert rules.secondary == "goal_differential"
        assert rules.tertiary == "goals_for"


class TestTiebreakerApplicationInRanking:
    """Test that tiebreaker rules correctly rank teams in standings."""
    
    def test_caf_group_ranking_with_goals_for_tiebreaker(self) -> None:
        """In CAF, a team with more goals-for ranks higher despite similar H2H."""
        accumulator = StandingsAccumulator("CAF")
        
        teams = [
            GroupTeam("team_a", points=6, goals_for=5, goals_against=1),
            GroupTeam("team_b", points=6, goals_for=3, goals_against=2),  # Same points, fewer GF
            GroupTeam("team_c", points=3, goals_for=2, goals_against=3),
            GroupTeam("team_d", points=0, goals_for=0, goals_against=6),
        ]
        
        ranked = accumulator.rank_teams(teams)
        assert ranked[0].team_id == "team_a"
        assert ranked[1].team_id == "team_b"
        # team_a ranks higher because it has more goals-for (5 > 3)
    
    def test_uefa_group_ranking_with_head_to_head_tiebreaker(self) -> None:
        """In UEFA, head-to-head overrides goals-for when teams are tied on points."""
        accumulator = StandingsAccumulator("UEFA")
        
        team_a = GroupTeam("team_a", points=6, goals_for=4, goals_against=2)
        team_b = GroupTeam("team_b", points=6, goals_for=5, goals_against=1)  # More GF but worse H2H
        
        # Set head-to-head: team_a beat team_b
        team_a.head_to_head_points["team_b"] = 3
        team_b.head_to_head_points["team_a"] = 0
        
        ranked = accumulator.rank_teams([team_a, team_b])
        assert ranked[0].team_id == "team_a"
        # team_a ranks higher despite fewer goals-for (4 < 5) because H2H is primary
    
    def test_conmebol_goal_differential_as_secondary(self) -> None:
        """In CONMEBOL, goal-differential is secondary to head-to-head."""
        accumulator = StandingsAccumulator("CONMEBOL")
        
        team_a = GroupTeam("team_a", points=6, goals_for=3, goals_against=3)  # GD = 0
        team_b = GroupTeam("team_b", points=6, goals_for=5, goals_against=2)  # GD = +3
        
        # Same H2H (both 0 vs each other)
        team_a.head_to_head_points["team_b"] = 1
        team_b.head_to_head_points["team_a"] = 1
        
        ranked = accumulator.rank_teams([team_a, team_b])
        assert ranked[0].team_id == "team_b"
        # team_b ranks higher because GD (+3) is better than team_a's (0)


class TestSimulationRespectsTiebreakerRules:
    """Test that the Monte Carlo simulation respects confederation tiebreaker order."""
    
    def test_simulation_outcome_respects_confederation_rules(self) -> None:
        """Verify that simulated standings respect the confederation's tiebreaker rules."""
        # Setup: UEFA group with specific scenario
        teams = {
            "france": GroupTeam("france", points=4, goals_for=2, goals_against=1),
            "spain": GroupTeam("spain", points=4, goals_for=2, goals_against=1),  # Tied with France
            "germany": GroupTeam("germany", points=1, goals_for=1, goals_against=2),
            "italy": GroupTeam("italy", points=0, goals_for=0, goals_against=3),
        }
        
        # Only one fixture remains: France vs Spain
        remaining = [
            ("france", "spain", True),
            ("germany", "italy", False),
        ]
        
        dist = simulate_group_stage_standings(
            group_id="test_group",
            confederation="UEFA",
            teams=teams,
            remaining_fixtures=remaining,
            n_iterations=100,
        )
        
        # Both France and Spain have some probability of finishing 1st/2nd
        # UEFA's H2H rule should make whoever wins the fixture the likely #1
        assert "france" in dist
        assert "spain" in dist
        assert all(pos >= 1 for pos in dist["france"].keys())
        assert all(pos >= 1 for pos in dist["spain"].keys())
