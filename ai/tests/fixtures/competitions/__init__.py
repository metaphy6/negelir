"""Synthetic competition fixtures for per-format predictor tests.

Per COMPETITIONS.md §9 Definition-of-Done, each format value must have at least
one happy-path predictor test. These fixtures provide synthetic (but realistic)
FixturePayloadV2 and Competition objects for each of the 8 format values.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SyntheticFixture:
    """Synthetic fixture for testing predictor behavior per competition format."""
    stable_id: str
    competition_id: str
    competition_format: str
    stage_id: Optional[str]
    venue_policy: str
    team_a: str
    team_b: str


# Fixtures for each format

FIXTURE_ROUND_ROBIN = SyntheticFixture(
    stable_id="fix_super_lig_round_robin_001",
    competition_id="super_lig_2024_25",
    competition_format="round_robin",
    stage_id=None,
    venue_policy="home_away",
    team_a="galatasaray",
    team_b="fenerbahce",
)

FIXTURE_SINGLE_KNOCKOUT = SyntheticFixture(
    stable_id="fix_turkiye_kupasi_r16_001",
    competition_id="turkiye_kupasi",
    competition_format="single_knockout",
    stage_id="round_of_16",
    venue_policy="home_away",
    team_a="galatasaray",
    team_b="karagumruk",
)

FIXTURE_TWO_LEG_KNOCKOUT = SyntheticFixture(
    stable_id="fix_ucl_ro16_leg1_001",
    competition_id="uefa_champions_league",
    competition_format="two_leg_knockout",
    stage_id="round_of_16",
    venue_policy="home_away",
    team_a="real_madrid",
    team_b="manchester_city",
)

FIXTURE_GROUP_ROUND_ROBIN = SyntheticFixture(
    stable_id="fix_ucl_group_g_001",
    competition_id="uefa_champions_league",
    competition_format="group_round_robin",
    stage_id="group_stage",
    venue_policy="home_away",
    team_a="galatasaray",
    team_b="real_madrid",
)

FIXTURE_GROUP_THEN_KNOCKOUT_GROUP = SyntheticFixture(
    stable_id="fix_euro_2024_group_a_001",
    competition_id="euro_2024",
    competition_format="group_then_knockout",
    stage_id="group_stage",
    venue_policy="host_country",
    team_a="turkey",
    team_b="italy",
)

FIXTURE_GROUP_THEN_KNOCKOUT_KO = SyntheticFixture(
    stable_id="fix_euro_2024_ro16_001",
    competition_id="euro_2024",
    competition_format="group_then_knockout",
    stage_id="round_of_16",
    venue_policy="neutral",
    team_a="turkey",
    team_b="georgia",
)

FIXTURE_MULTI_STAGE_QUALIFIER = SyntheticFixture(
    stable_id="fix_ucl_qualifier_r2_001",
    competition_id="uefa_champions_league",
    competition_format="multi_stage_qualifier",
    stage_id="round_2",
    venue_policy="home_away",
    team_a="fenerbahce",
    team_b="salzburg",
)

FIXTURE_FINAL_ONLY = SyntheticFixture(
    stable_id="fix_uefa_super_cup_2024_001",
    competition_id="uefa_super_cup",
    competition_format="final_only",
    stage_id="final",
    venue_policy="neutral",
    team_a="real_madrid",
    team_b="atalanta",
)

FIXTURE_PLAYOFF_BRACKET = SyntheticFixture(
    stable_id="fix_mls_cup_2024_conf_finals_001",
    competition_id="mls_cup_2024",
    competition_format="playoff_bracket",
    stage_id="conference_finals",
    venue_policy="home_away",
    team_a="mls_east_winner",
    team_b="mls_semi_finalist",
)

# Mapping for quick lookup
FIXTURES_BY_FORMAT = {
    "round_robin": FIXTURE_ROUND_ROBIN,
    "single_knockout": FIXTURE_SINGLE_KNOCKOUT,
    "two_leg_knockout": FIXTURE_TWO_LEG_KNOCKOUT,
    "group_round_robin": FIXTURE_GROUP_ROUND_ROBIN,
    "group_then_knockout": FIXTURE_GROUP_THEN_KNOCKOUT_GROUP,  # default: group portion
    "multi_stage_qualifier": FIXTURE_MULTI_STAGE_QUALIFIER,
    "final_only": FIXTURE_FINAL_ONLY,
    "playoff_bracket": FIXTURE_PLAYOFF_BRACKET,
}


def get_synthetic_fixture(format_: str) -> SyntheticFixture:
    """Fetch a synthetic fixture for a given competition format.
    
    Args:
        format_: Competition format (e.g., "round_robin", "single_knockout").
    
    Returns:
        SyntheticFixture with realistic team/competition pairing.
    
    Raises:
        ValueError: if format_ is not recognized.
    """
    if format_ not in FIXTURES_BY_FORMAT:
        raise ValueError(
            f"Unknown format: {format_}. Supported: {sorted(FIXTURES_BY_FORMAT.keys())}"
        )
    return FIXTURES_BY_FORMAT[format_]
