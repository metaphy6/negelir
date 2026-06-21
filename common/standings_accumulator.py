"""Phase 19.5 — Group standings accumulator with confederation-specific tiebreakers.

Provides simulate_group_stage_standings(group_id, confederation, remaining_fixtures, n_iterations)
for Monte Carlo simulation of final standings positions per team. Uses confederation-specific
tiebreaker rules: CAF prioritizes goals-for; UEFA prioritizes head-to-head; etc.
Simulation is incremental: each new fixture result narrows the distribution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from collections import defaultdict
import random


@dataclass(frozen=True)
class TeamFixture:
    """A team's fixture to be simulated."""
    team_id: str
    opponent_id: str
    is_home: bool  # True if this team is home


@dataclass
class GroupTeam:
    """A team's standing state during standings simulation."""
    team_id: str
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    matches_played: int = 0
    head_to_head_points: Dict[str, int] = field(default_factory=dict)  # opponent_id -> points vs that opponent


@dataclass(frozen=True)
class ConfederationTiebreakerRules:
    """Tiebreaker order for a confederation's group stage."""
    confederation: str
    primary: str  # "goals_for", "head_to_head", "points"
    secondary: str  # "goals_for", "head_to_head", "goal_differential"
    tertiary: str  # "goal_differential", "away_goals", "draw"
    
    # Standard confederation rules
    @staticmethod
    def for_confederation(conf: str) -> ConfederationTiebreakerRules:
        """Get the standard tiebreaker rules for a confederation."""
        rules = {
            "CAF": ConfederationTiebreakerRules("CAF", "goals_for", "head_to_head", "goal_differential"),
            "UEFA": ConfederationTiebreakerRules("UEFA", "head_to_head", "goals_for", "goal_differential"),
            "CONMEBOL": ConfederationTiebreakerRules("CONMEBOL", "head_to_head", "goal_differential", "goals_for"),
            "AFC": ConfederationTiebreakerRules("AFC", "goals_for", "head_to_head", "goal_differential"),
            "CONCACAF": ConfederationTiebreakerRules("CONCACAF", "head_to_head", "goals_for", "goal_differential"),
            "OFC": ConfederationTiebreakerRules("OFC", "goals_for", "head_to_head", "goal_differential"),
        }
        return rules.get(conf, ConfederationTiebreakerRules(conf, "points", "goals_for", "goal_differential"))


class StandingsAccumulator:
    """Accumulates group standings with confederation-specific tiebreaker logic."""
    
    def __init__(self, confederation: str):
        self.confederation = confederation
        self.tiebreaker_rules = ConfederationTiebreakerRules.for_confederation(confederation)
    
    def _compare_teams(self, team_a: GroupTeam, team_b: GroupTeam) -> int:
        """Compare two teams by tiebreaker rules.
        
        Returns:
            1 if team_a ranks higher
            -1 if team_b ranks higher
            0 if tied
        """
        # Primary tiebreaker
        cmp = self._compare_by_criterion(team_a, team_b, self.tiebreaker_rules.primary)
        if cmp != 0:
            return cmp
        
        # Secondary tiebreaker
        cmp = self._compare_by_criterion(team_a, team_b, self.tiebreaker_rules.secondary)
        if cmp != 0:
            return cmp
        
        # Tertiary tiebreaker
        cmp = self._compare_by_criterion(team_a, team_b, self.tiebreaker_rules.tertiary)
        return cmp
    
    def _compare_by_criterion(self, team_a: GroupTeam, team_b: GroupTeam, criterion: str) -> int:
        """Compare two teams by a specific criterion.
        
        Returns:
            1 if team_a ranks higher
            -1 if team_b ranks higher
            0 if tied by this criterion
        """
        if criterion == "points":
            if team_a.points > team_b.points:
                return 1
            elif team_a.points < team_b.points:
                return -1
        
        elif criterion == "goals_for":
            if team_a.goals_for > team_b.goals_for:
                return 1
            elif team_a.goals_for < team_b.goals_for:
                return -1
        
        elif criterion == "goal_differential":
            diff_a = team_a.goals_for - team_a.goals_against
            diff_b = team_b.goals_for - team_b.goals_against
            if diff_a > diff_b:
                return 1
            elif diff_a < diff_b:
                return -1
        
        elif criterion == "head_to_head":
            # Head-to-head points for mutual comparison
            h2h_a = team_a.head_to_head_points.get(team_b.team_id, 0)
            h2h_b = team_b.head_to_head_points.get(team_a.team_id, 0)
            if h2h_a > h2h_b:
                return 1
            elif h2h_a < h2h_b:
                return -1
        
        return 0
    
    def rank_teams(self, teams: List[GroupTeam]) -> List[GroupTeam]:
        """Rank teams by tiebreaker rules, highest to lowest."""
        from functools import cmp_to_key
        return sorted(teams, key=cmp_to_key(lambda a, b: -self._compare_teams(a, b)))
    
    def simulate_group_stage_standings(
        self,
        group_id: str,
        teams: Dict[str, GroupTeam],
        remaining_fixtures: List[tuple[str, str, bool]],  # (home_id, away_id, is_simulated)
        n_iterations: int = 10000,
    ) -> Dict[str, Dict[int, float]]:
        """Simulate final group standings over remaining fixtures.
        
        Args:
            group_id: Group identifier
            teams: Dict of team_id -> GroupTeam with current standing
            remaining_fixtures: List of (home_id, away_id, is_simulated) tuples
            n_iterations: Number of Monte Carlo iterations
            
        Returns:
            Dict mapping team_id -> {position: probability}
            Example: {"france": {1: 0.92, 2: 0.08}, "netherlands": {1: 0.08, 2: 0.92}}
        """
        position_distribution: Dict[str, Dict[int, float]] = {
            team_id: defaultdict(float) for team_id in teams
        }
        
        for _ in range(n_iterations):
            # Clone current standings
            sim_teams = {
                team_id: GroupTeam(
                    team_id=team.team_id,
                    points=team.points,
                    goals_for=team.goals_for,
                    goals_against=team.goals_against,
                    matches_played=team.matches_played,
                    head_to_head_points=team.head_to_head_points.copy()
                )
                for team_id, team in teams.items()
            }
            
            # Simulate remaining fixtures
            for home_id, away_id, is_simulated in remaining_fixtures:
                if not is_simulated:
                    continue  # Skip already-played fixtures
                
                # Simple Poisson-like simulation: probability of home win, draw, away win
                outcome = random.choices(
                    ["home_win", "draw", "away_win"],
                    weights=[0.45, 0.25, 0.30],  # Rough averages (home advantage bias)
                    k=1
                )[0]
                
                home_team = sim_teams[home_id]
                away_team = sim_teams[away_id]
                
                if outcome == "home_win":
                    home_goals = random.randint(1, 3)
                    away_goals = random.randint(0, 1)
                    home_team.points += 3
                    h2h_update = 3
                elif outcome == "draw":
                    home_goals = random.randint(0, 2)
                    away_goals = home_goals
                    home_team.points += 1
                    away_team.points += 1
                    h2h_update = 1
                else:  # away_win
                    home_goals = random.randint(0, 1)
                    away_goals = random.randint(1, 3)
                    away_team.points += 3
                    h2h_update = 0
                
                home_team.goals_for += home_goals
                home_team.goals_against += away_goals
                home_team.matches_played += 1
                
                away_team.goals_for += away_goals
                away_team.goals_against += home_goals
                away_team.matches_played += 1
                
                # Track head-to-head
                home_team.head_to_head_points[away_id] = home_team.head_to_head_points.get(away_id, 0) + h2h_update
                away_team.head_to_head_points[home_id] = away_team.head_to_head_points.get(home_id, 0) + (
                    3 if outcome == "away_win" else (1 if outcome == "draw" else 0)
                )
            
            # Rank teams
            ranked = self.rank_teams(list(sim_teams.values()))
            for position, team in enumerate(ranked, start=1):
                position_distribution[team.team_id][position] += 1.0
        
        # Normalize to probabilities
        for team_id in position_distribution:
            for position in position_distribution[team_id]:
                position_distribution[team_id][position] /= n_iterations
        
        return {team_id: dict(pos_dist) for team_id, pos_dist in position_distribution.items()}


def simulate_group_stage_standings(
    group_id: str,
    confederation: str,
    teams: Dict[str, GroupTeam],
    remaining_fixtures: List[tuple[str, str, bool]],
    n_iterations: int = 10000,
) -> Dict[str, Dict[int, float]]:
    """Top-level function for group stage standings simulation.
    
    Args:
        group_id: Group identifier
        confederation: Confederation (determines tiebreaker rules)
        teams: Dict of team_id -> GroupTeam with current standing
        remaining_fixtures: List of (home_id, away_id, is_simulated) tuples
        n_iterations: Number of Monte Carlo iterations (default 10000)
        
    Returns:
        Dict mapping team_id -> {position: probability}
    """
    accumulator = StandingsAccumulator(confederation)
    return accumulator.simulate_group_stage_standings(group_id, teams, remaining_fixtures, n_iterations)
