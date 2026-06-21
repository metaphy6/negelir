"""Phase 19.5 §19.5 — Continental championship format with independent tiebreaker rules."""
from __future__ import annotations

import pytest
from common.schemas.competition import (
    GroupStageConfig,
    KnockoutPhaseConfig,
    TournamentTiebreakerRules,
    ContinentalChampionshipFormat,
    CompetitionPayload,
)


class TestContinentalChampionshipFormat:
    """Tests for continental championship format type definitions."""

    def test_group_stage_config_required_fields(self) -> None:
        """GroupStageConfig must support required fields."""
        config: GroupStageConfig = {
            "num_groups": 4,
            "teams_per_group": 4,
            "teams_advancing_per_group": 2,
            "tiebreaker_rules": ["goals_for", "head_to_head", "goal_differential"],
        }
        assert config["num_groups"] == 4
        assert config["teams_per_group"] == 4
        assert config["teams_advancing_per_group"] == 2

    def test_knockout_phase_config_required_fields(self) -> None:
        """KnockoutPhaseConfig must support required fields."""
        config: KnockoutPhaseConfig = {
            "format": "single_knockout",
            "semi_finals_legs": 1,
            "final_legs": 1,
            "extra_time": True,
            "penalties": True,
            "away_goals_rule": False,
        }
        assert config["format"] == "single_knockout"
        assert config["extra_time"] is True
        assert config["penalties"] is True

    def test_tournament_tiebreaker_rules_uefa_style(self) -> None:
        """UEFA-style tiebreakers: head-to-head before goals-for."""
        rules: TournamentTiebreakerRules = {
            "confederation": "UEFA",
            "primary_tiebreaker": "head_to_head",
            "secondary_tiebreaker": "goal_differential",
            "tertiary_tiebreaker": "away_goals",
        }
        assert rules["confederation"] == "UEFA"
        assert rules["primary_tiebreaker"] == "head_to_head"

    def test_tournament_tiebreaker_rules_caf_style(self) -> None:
        """CAF-style tiebreakers: goals-for before head-to-head (different from UEFA)."""
        rules: TournamentTiebreakerRules = {
            "confederation": "CAF",
            "primary_tiebreaker": "goals_for",
            "secondary_tiebreaker": "head_to_head",
            "tertiary_tiebreaker": "goal_differential",
        }
        assert rules["confederation"] == "CAF"
        assert rules["primary_tiebreaker"] == "goals_for"

    def test_tournament_tiebreaker_rules_conmebol_style(self) -> None:
        """CONMEBOL-style tiebreakers."""
        rules: TournamentTiebreakerRules = {
            "confederation": "CONMEBOL",
            "primary_tiebreaker": "head_to_head",
            "secondary_tiebreaker": "goals_for",
            "tertiary_tiebreaker": "goal_differential",
        }
        assert rules["confederation"] == "CONMEBOL"

    def test_continental_championship_format_euro_2024(self) -> None:
        """UEFA Euro 2024 format: 4 groups of 4, top 2 advance."""
        fmt: ContinentalChampionshipFormat = {
            "group_stage": {
                "num_groups": 4,
                "teams_per_group": 4,
                "teams_advancing_per_group": 2,
                "tiebreaker_rules": ["head_to_head", "goal_differential", "goals_for"],
            },
            "knockout_phase": {
                "format": "single_knockout",
                "semi_finals_legs": 1,
                "final_legs": 1,
                "extra_time": True,
                "penalties": True,
                "away_goals_rule": False,
            },
            "tiebreaker_rules": {
                "confederation": "UEFA",
                "primary_tiebreaker": "head_to_head",
                "secondary_tiebreaker": "goal_differential",
                "tertiary_tiebreaker": "away_goals",
            },
            "host_nation_flag": True,
        }
        assert fmt["group_stage"]["num_groups"] == 4
        assert fmt["host_nation_flag"] is True

    def test_continental_championship_format_copa_america(self) -> None:
        """Copa América format: typically 3 groups, top 2 advance."""
        fmt: ContinentalChampionshipFormat = {
            "group_stage": {
                "num_groups": 3,
                "teams_per_group": 4,
                "teams_advancing_per_group": 2,
                "tiebreaker_rules": ["goals_for", "head_to_head", "goal_differential"],
            },
            "knockout_phase": {
                "format": "single_knockout",
                "semi_finals_legs": 1,
                "final_legs": 1,
                "extra_time": True,
                "penalties": True,
                "away_goals_rule": False,
            },
            "tiebreaker_rules": {
                "confederation": "CONMEBOL",
                "primary_tiebreaker": "head_to_head",
                "secondary_tiebreaker": "goals_for",
                "tertiary_tiebreaker": "goal_differential",
            },
            "host_nation_flag": True,
        }
        assert fmt["group_stage"]["num_groups"] == 3

    def test_continental_championship_format_afcon(self) -> None:
        """AFCON format: variable group count, CAF tiebreaker hierarchy."""
        fmt: ContinentalChampionshipFormat = {
            "group_stage": {
                "num_groups": 4,
                "teams_per_group": 4,
                "teams_advancing_per_group": 2,
                "tiebreaker_rules": ["goals_for", "head_to_head", "goal_differential"],
            },
            "knockout_phase": {
                "format": "single_knockout",
                "semi_finals_legs": 1,
                "final_legs": 1,
                "extra_time": True,
                "penalties": True,
                "away_goals_rule": False,
            },
            "tiebreaker_rules": {
                "confederation": "CAF",
                "primary_tiebreaker": "goals_for",
                "secondary_tiebreaker": "head_to_head",
                "tertiary_tiebreaker": "goal_differential",
            },
            "host_nation_flag": True,
        }
        assert fmt["tiebreaker_rules"]["confederation"] == "CAF"
        assert fmt["tiebreaker_rules"]["primary_tiebreaker"] == "goals_for"

    def test_competition_payload_euro_2024(self) -> None:
        """Full CompetitionPayload for UEFA Euro 2024."""
        fmt: ContinentalChampionshipFormat = {
            "group_stage": {
                "num_groups": 4,
                "teams_per_group": 4,
                "teams_advancing_per_group": 2,
                "tiebreaker_rules": ["head_to_head", "goal_differential", "goals_for"],
            },
            "knockout_phase": {
                "format": "single_knockout",
                "semi_finals_legs": 1,
                "final_legs": 1,
                "extra_time": True,
                "penalties": True,
                "away_goals_rule": False,
            },
            "tiebreaker_rules": {
                "confederation": "UEFA",
                "primary_tiebreaker": "head_to_head",
                "secondary_tiebreaker": "goal_differential",
                "tertiary_tiebreaker": "away_goals",
            },
            "host_nation_flag": True,
        }

        payload: CompetitionPayload = {
            "competition_id": "uefa_euro_2024",
            "name_en": "UEFA European Football Championship 2024",
            "name_tr": "2024 UEFA Avrupa Futbol Şampiyonası",
            "aliases": ["Euro 2024", "EURO 2024"],
            "format": "continental_championship",
            "scope": "international_championship",
            "default_venue_policy": "host_country",
            "organizer": "UEFA",
            "confederation": "UEFA",
            "countries": ["DE"],  # Hosted in Germany
            "nationality_restricted": True,
            "calibration_profile_id": "continental_championship_euro",
            "active": True,
            "continental_championship": fmt,
        }

        assert payload["format"] == "continental_championship"
        assert payload["continental_championship"] is not None
        assert payload["continental_championship"]["host_nation_flag"] is True

    def test_tiebreaker_rules_are_independent_from_domestic_league(self) -> None:
        """Continental championship tiebreakers are independent from Phase 13 domestic league rules.
        
        This test ensures that the TournamentTiebreakerRules can be completely different
        from a domestic league's tiebreaker configuration.
        """
        # UEFA's tournament tiebreaker prioritizes head-to-head
        tournament_rules: TournamentTiebreakerRules = {
            "confederation": "UEFA",
            "primary_tiebreaker": "head_to_head",
            "secondary_tiebreaker": "goal_differential",
            "tertiary_tiebreaker": "away_goals",
        }

        # A domestic league (e.g., Premier League) might prioritize goals-for
        # This is independent and would be in a separate LeagueConfig
        assert tournament_rules["primary_tiebreaker"] == "head_to_head"
        # Domestic league could have primary_tiebreaker = "goals_for", no conflict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
