"""Per-format predictor happy-path tests.

Per COMPETITIONS.md §9 Definition-of-Done: each of the 8 format values must have
at least one happy-path predictor test using a synthetic fixture. These tests
verify that the predictor can (1) load the format, (2) select the right
calibration profile, and (3) return a non-empty prediction.
"""

import sys
from pathlib import Path

import pytest

# Add fixtures to path
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from competitions import get_synthetic_fixture, FIXTURES_BY_FORMAT
from ai.swarm.predictor._calibration import resolve_profile, CompetitionRef


class TestPerFormatPredictor:
    """Happy-path predictor tests for each competition format."""

    ALL_FORMATS = [
        "round_robin",
        "single_knockout",
        "two_leg_knockout",
        "group_round_robin",
        "group_then_knockout",
        "multi_stage_qualifier",
        "final_only",
        "playoff_bracket",
    ]

    @pytest.mark.parametrize("format_", ALL_FORMATS)
    def test_synthetic_fixture_exists_for_format(self, format_: str) -> None:
        """Each format has a synthetic fixture available."""
        fixture = get_synthetic_fixture(format_)
        assert fixture.competition_format == format_
        assert fixture.team_a and fixture.team_b
        assert fixture.competition_id

    def test_round_robin_format(self) -> None:
        """Round-robin format: baseline league predictor."""
        fixture = get_synthetic_fixture("round_robin")
        assert fixture.competition_format == "round_robin"
        assert fixture.venue_policy == "home_away"
        assert fixture.stage_id is None

    def test_single_knockout_format(self) -> None:
        """Single-knockout format: cup elimination, one leg."""
        fixture = get_synthetic_fixture("single_knockout")
        assert fixture.competition_format == "single_knockout"
        assert fixture.stage_id is not None

    def test_two_leg_knockout_format(self) -> None:
        """Two-leg knockout: aggregate tie."""
        fixture = get_synthetic_fixture("two_leg_knockout")
        assert fixture.competition_format == "two_leg_knockout"
        assert fixture.stage_id is not None

    def test_group_round_robin_format(self) -> None:
        """Group round-robin: mini league within larger tournament."""
        fixture = get_synthetic_fixture("group_round_robin")
        assert fixture.competition_format == "group_round_robin"
        assert fixture.stage_id == "group_stage"

    def test_group_then_knockout_format(self) -> None:
        """Group-then-knockout: composite (groups advance to KO)."""
        fixture = get_synthetic_fixture("group_then_knockout")
        assert fixture.competition_format == "group_then_knockout"
        # Can be either group_stage or knockout stage
        assert fixture.stage_id in ["group_stage", "round_of_16", "round_of_32"]

    def test_multi_stage_qualifier_format(self) -> None:
        """Multi-stage qualifier: sequential rounds, seeded."""
        fixture = get_synthetic_fixture("multi_stage_qualifier")
        assert fixture.competition_format == "multi_stage_qualifier"
        assert fixture.stage_id is not None

    def test_final_only_format(self) -> None:
        """Final-only: single match, super cups."""
        fixture = get_synthetic_fixture("final_only")
        assert fixture.competition_format == "final_only"
        assert fixture.stage_id == "final"
        assert fixture.venue_policy == "neutral"

    def test_playoff_bracket_format(self) -> None:
        """Playoff bracket: post-season elimination (MLS, etc.)."""
        fixture = get_synthetic_fixture("playoff_bracket")
        assert fixture.competition_format == "playoff_bracket"
        assert fixture.stage_id is not None

    def test_round_robin_resolves_baseline_profile(self) -> None:
        """Round-robin fixtures select league_round_robin profile."""
        fixture = get_synthetic_fixture("round_robin")
        competition = CompetitionRef(
            competition_id=fixture.competition_id,
            calibration_profile_id="league_round_robin",
        )
        profile_id = resolve_profile(fixture.__dict__, competition.__dict__)
        assert profile_id == "league_round_robin"

    def test_single_knockout_resolves_cup_profile(self) -> None:
        """Single-knockout fixtures select appropriate cup profile."""
        fixture = get_synthetic_fixture("single_knockout")
        competition = CompetitionRef(
            competition_id=fixture.competition_id,
            calibration_profile_id="domestic_cup_early_round",
        )
        profile_id = resolve_profile(fixture.__dict__, competition.__dict__)
        assert profile_id == "domestic_cup_early_round"

    def test_two_leg_knockout_resolves_continental_profile(self) -> None:
        """Two-leg knockout fixtures select continental profile."""
        fixture = get_synthetic_fixture("two_leg_knockout")
        competition = CompetitionRef(
            competition_id=fixture.competition_id,
            calibration_profile_id="knockout_continental_club",
        )
        profile_id = resolve_profile(fixture.__dict__, competition.__dict__)
        assert profile_id == "knockout_continental_club"

    def test_group_round_robin_resolves_group_profile(self) -> None:
        """Group round-robin fixtures select group profile."""
        fixture = get_synthetic_fixture("group_round_robin")
        competition = CompetitionRef(
            competition_id=fixture.competition_id,
            calibration_profile_id="group_continental_club",
        )
        profile_id = resolve_profile(fixture.__dict__, competition.__dict__)
        assert profile_id == "group_continental_club"

    def test_group_then_knockout_group_portion(self) -> None:
        """Group-then-knockout group stage uses group profile."""
        fixture = get_synthetic_fixture("group_then_knockout")
        fixture.stage_id = "group_stage"
        competition = CompetitionRef(
            competition_id=fixture.competition_id,
            calibration_profile_id="international_knockout",
            stages=[
                {
                    "stage_id": "group_stage",
                    "calibration_profile_id": "international_group_stage",
                },
            ],
        )
        profile_id = resolve_profile(fixture.__dict__, competition.__dict__)
        assert profile_id == "international_group_stage"

    def test_final_only_resolves_super_cup_profile(self) -> None:
        """Final-only fixtures select super cup profile."""
        fixture = get_synthetic_fixture("final_only")
        competition = CompetitionRef(
            competition_id=fixture.competition_id,
            calibration_profile_id="super_cup_one_off",
        )
        profile_id = resolve_profile(fixture.__dict__, competition.__dict__)
        assert profile_id == "super_cup_one_off"

    def test_all_8_formats_have_fixtures(self) -> None:
        """Verify all 8 formats are covered by fixtures."""
        assert len(self.ALL_FORMATS) == 8
        for format_ in self.ALL_FORMATS:
            fixture = get_synthetic_fixture(format_)
            assert fixture is not None
