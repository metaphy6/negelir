"""Test calibration profile resolution priority rule.

Per COMPETITIONS.md §4.1, the resolution priority is:
1. Stage-level override (if stage has calibration_profile_id)
2. Competition-level default (always present)
"""

import pytest
from swarm.predictor._calibration import (
    resolve_profile,
    FixtureRef,
    CompetitionRef,
    CompetitionStageRef,
)


class TestProfileResolutionPriority:
    """Resolution priority: stage > competition > error."""

    def test_competition_level_profile_is_default(self) -> None:
        """When no stage is specified, use competition-level profile."""
        fixture = FixtureRef(
            stable_id="fix_001",
            competition_id="ucl",
            stage_id=None,
            venue_policy="home_away",
        )
        competition = CompetitionRef(
            competition_id="ucl",
            calibration_profile_id="knockout_continental_club",
            stages=None,
        )
        assert resolve_profile(fixture, competition) == "knockout_continental_club"

    def test_stage_level_overrides_competition(self) -> None:
        """When fixture.stage_id matches a stage with profile_id, use stage profile."""
        fixture = FixtureRef(
            stable_id="fix_002",
            competition_id="ucl",
            stage_id="group_stage",
            venue_policy="home_away",
        )
        competition = CompetitionRef(
            competition_id="ucl",
            calibration_profile_id="knockout_continental_club",
            stages=[
                CompetitionStageRef(
                    stage_id="group_stage",
                    calibration_profile_id="group_continental_club",
                ),
                CompetitionStageRef(
                    stage_id="round_of_16",
                    calibration_profile_id=None,
                ),
            ],
        )
        assert resolve_profile(fixture, competition) == "group_continental_club"

    def test_stage_without_profile_inherits_competition(self) -> None:
        """When stage has no profile_id, fall back to competition profile."""
        fixture = FixtureRef(
            stable_id="fix_003",
            competition_id="ucl",
            stage_id="round_of_16",
            venue_policy="home_away",
        )
        competition = CompetitionRef(
            competition_id="ucl",
            calibration_profile_id="knockout_continental_club",
            stages=[
                CompetitionStageRef(
                    stage_id="group_stage",
                    calibration_profile_id="group_continental_club",
                ),
                CompetitionStageRef(
                    stage_id="round_of_16",
                    calibration_profile_id=None,  # no override
                ),
            ],
        )
        assert resolve_profile(fixture, competition) == "knockout_continental_club"

    def test_stage_id_not_found_uses_competition_profile(self) -> None:
        """When fixture.stage_id doesn't match any stage, use competition profile."""
        fixture = FixtureRef(
            stable_id="fix_004",
            competition_id="ucl",
            stage_id="final",
            venue_policy="home_away",
        )
        competition = CompetitionRef(
            competition_id="ucl",
            calibration_profile_id="knockout_continental_club",
            stages=[
                CompetitionStageRef(
                    stage_id="group_stage",
                    calibration_profile_id="group_continental_club",
                ),
            ],
        )
        assert resolve_profile(fixture, competition) == "knockout_continental_club"

    def test_missing_competition_profile_id_raises(self) -> None:
        """Refuse to resolve if competition has no calibration_profile_id."""
        fixture = FixtureRef(
            stable_id="fix_005",
            competition_id="unknown",
            stage_id=None,
            venue_policy="home_away",
        )
        competition = CompetitionRef(
            competition_id="unknown",
            calibration_profile_id="",  # empty/missing
            stages=None,
        )
        with pytest.raises(ValueError, match="has no calibration_profile_id"):
            resolve_profile(fixture, competition)

    def test_resolution_works_with_dicts(self) -> None:
        """Resolution accepts plain dicts in place of dataclass refs."""
        fixture_dict = {
            "stable_id": "fix_006",
            "competition_id": "euro",
            "stage_id": "group_stage",
            "venue_policy": "neutral",
        }
        competition_dict = {
            "competition_id": "euro",
            "calibration_profile_id": "international_knockout",
            "stages": [
                {
                    "stage_id": "group_stage",
                    "calibration_profile_id": "international_group_stage",
                },
            ],
        }
        assert (
            resolve_profile(fixture_dict, competition_dict)
            == "international_group_stage"
        )

    def test_resolution_mixed_types(self) -> None:
        """Resolution accepts mixed dataclass + dict inputs."""
        fixture = FixtureRef(
            stable_id="fix_007",
            competition_id="wc",
            stage_id="knockout",
            venue_policy="neutral",
        )
        competition_dict = {
            "competition_id": "wc",
            "calibration_profile_id": "international_knockout",
            "stages": [
                {
                    "stage_id": "group_stage",
                    "calibration_profile_id": "international_group_stage",
                },
                {"stage_id": "knockout", "calibration_profile_id": None},
            ],
        }
        assert resolve_profile(fixture, competition_dict) == "international_knockout"
