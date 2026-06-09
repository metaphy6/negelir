"""Calibration profile resolution for competition format-aware prediction.

Per COMPETITIONS.md §4.1, this module implements the deterministic, LLM-free
three-step resolution rule for selecting a CalibrationProfile for any fixture.
"""

from typing import Any, Optional
from dataclasses import dataclass


# Type hints for Competition and Fixture (minimal shape for resolution).
# Full schemas live in common/schemas/ and DATA_PIPELINE.md.

@dataclass(frozen=True)
class CompetitionStageRef:
    """Minimal stage reference for resolution logic."""
    stage_id: str
    calibration_profile_id: Optional[str] = None


@dataclass(frozen=True)
class CompetitionRef:
    """Minimal competition reference for resolution logic."""
    competition_id: str
    calibration_profile_id: str
    stages: Optional[list[CompetitionStageRef]] = None


@dataclass(frozen=True)
class FixtureRef:
    """Minimal fixture reference for resolution logic."""
    stable_id: str
    competition_id: str
    venue_policy: str = "home_away"  # "home_away", "neutral", "host_country", "bubble"
    stage_id: Optional[str] = None


def resolve_profile(
    fixture: FixtureRef | dict[str, Any],
    competition: CompetitionRef | dict[str, Any],
) -> str:
    """Resolve calibration profile ID for a fixture using deterministic rules.

    Args:
        fixture: FixturePayloadV2 dict or FixtureRef with stage_id, venue_policy.
        competition: Competition dict or CompetitionRef with calibration_profile_id
                     and optional stages list.

    Returns:
        calibration_profile_id: str (e.g., "knockout_continental_club").

    Resolution rule (COMPETITIONS.md §4.1):
        1. Start with competition.calibration_profile_id (always set).
        2. If fixture.stage_id matches a stage in competition.stages and that
           stage has its own calibration_profile_id, that wins.
        3. (Note: venue_policy override is applied at prediction time in
           LeagueConfig.elo_home_advantage evaluation, not here. This function
           returns the profile ID; the predictor applies the profile's
           zero_home_advantage_when_venue_in clause.)

    Examples:
        >>> fixture = FixtureRef(
        ...     stable_id="...",
        ...     competition_id="uefa_champions_league",
        ...     stage_id="round_of_16",
        ...     venue_policy="home_away",
        ... )
        >>> competition = CompetitionRef(
        ...     competition_id="uefa_champions_league",
        ...     calibration_profile_id="knockout_continental_club",
        ...     stages=[
        ...         CompetitionStageRef(
        ...             stage_id="group_stage",
        ...             calibration_profile_id="group_continental_club",
        ...         ),
        ...         CompetitionStageRef(
        ...             stage_id="round_of_16",
        ...             calibration_profile_id=None,  # inherits from competition
        ...         ),
        ...     ],
        ... )
        >>> resolve_profile(fixture, competition)
        'knockout_continental_club'
    """
    # Normalize inputs to dicts for uniform access.
    fixture_dict = fixture if isinstance(fixture, dict) else fixture.__dict__
    competition_dict = competition if isinstance(competition, dict) else competition.__dict__

    # Step 1: Start with competition-level profile (always present).
    profile_id = competition_dict.get("calibration_profile_id")
    if not profile_id:
        raise ValueError(
            f"competition {competition_dict.get('competition_id', '?')} "
            "has no calibration_profile_id"
        )

    # Step 2: Check for stage-level override.
    fixture_stage_id = fixture_dict.get("stage_id")
    if fixture_stage_id:
        stages = competition_dict.get("stages") or []
        for stage in stages:
            stage_dict = stage if isinstance(stage, dict) else stage.__dict__
            if stage_dict.get("stage_id") == fixture_stage_id:
                stage_profile_id = stage_dict.get("calibration_profile_id")
                if stage_profile_id:
                    profile_id = stage_profile_id
                    break

    return profile_id
