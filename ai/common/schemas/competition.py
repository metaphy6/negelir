"""Phase 13.2 — Competition TypedDicts for phase-1 (reference plane).

Per COMPETITIONS.md §2, competitions are Reference-plane entities with
payload schema v1 defined here. JSONSchema mirror at
ai/common/schemas/feeds/competition.v1.json for Phase 16 emitter.
"""
from typing import Literal, TypedDict


class CompetitionStage(TypedDict, total=False):
    """A stage within a composite competition format (e.g. group stage → knockout).
    
    Used when competition.format is one of:
    - group_round_robin
    - group_then_knockout
    - multi_stage_qualifier
    
    All fields are required (total=False indicates optional in the TypedDict
    protocol, but this type should always be fully populated in practice).
    """

    stage_id: str
    """Unique within the competition, e.g. 'group_stage', 'round_of_16'."""

    order: int
    """0-indexed; stages run in order. Determines the sequence of fixtures."""

    format: Literal[
        "round_robin",
        "single_knockout",
        "two_leg_knockout",
        "group_round_robin",
    ]
    """Format of this stage. May differ from the parent competition format."""

    legs: int
    """1 for single-leg, 2 for two-leg (e.g., knockout rounds)."""

    venue_policy: Literal["home_away", "neutral", "host_country", "bubble"]
    """Venue policy for this stage. May override competition.default_venue_policy."""

    away_goals_rule_active: bool
    """True if the away-goals rule applies (historical, era-aware)."""

    extra_time: bool
    """True if extra time is played (for knockout stages)."""

    penalties: bool
    """True if penalties decide if extra time is insufficient."""

    seeding: Literal["draw", "bracket", "none"]
    """How entrants are seeded into this stage."""


class CompetitionPayload(TypedDict, total=False):
    """Phase 13.2 — Competition reference-plane payload (Record.record_type='competition').

    Per COMPETITIONS.md §2.1, this is the payload schema for every competition
    (league, cup, tournament, etc.). It embeds the competition's format, scope,
    and calibration profile so the predictor can make format-aware predictions.

    This TypedDict is the Python side of the JSONSchema at
    ai/common/schemas/feeds/competition.v1.json.
    """

    # Identity
    competition_id: str
    """Canonical, globally unique identifier, e.g. 'uefa_champions_league'."""

    name_en: str
    """English display name, e.g. 'UEFA Champions League'."""

    name_tr: str
    """Turkish display name, e.g. 'UEFA Şampiyonlar Ligi'."""

    aliases: list[str]
    """Alternative names, abbreviations, e.g. ['UCL', 'Şampiyonlar Ligi']."""

    # Axis A — format (COMPETITIONS.md §1.1)
    format: Literal[
        "round_robin",
        "single_knockout",
        "two_leg_knockout",
        "group_round_robin",
        "group_then_knockout",
        "multi_stage_qualifier",
        "final_only",
        "playoff_bracket",
    ]
    """Competition format determines calibration profile and prediction strategy."""

    # Axis B — scope (COMPETITIONS.md §1.2)
    scope: Literal[
        "domestic_league",
        "domestic_cup",
        "domestic_super_cup",
        "continental_club",
        "continental_super_cup",
        "intercontinental_club",
        "international_friendly",
        "international_qualifier",
        "international_championship",
    ]
    """Competition scope (league, cup, international, etc.)."""

    # Axis C — venue policy (COMPETITIONS.md §1.3)
    default_venue_policy: Literal["home_away", "neutral", "host_country", "bubble"]
    """Default venue policy for this competition (may be overridden per stage)."""

    # Metadata
    organizer: str
    """Organization running the competition, e.g. 'TFF', 'UEFA', 'FIFA'."""

    confederation: str | None
    """Continental confederation (UEFA, CONMEBOL, etc.) or None for domestic."""

    countries: list[str]
    """ISO-3166 alpha-2 country codes. ['TR'] for domestic, multiple for continental."""

    nationality_restricted: bool
    """True for international_* competitions; False for club competitions."""

    # Calibration
    calibration_profile_id: str
    """ID of the calibration profile to apply (e.g. 'knockout_continental_club')."""

    # Stage map (composite formats)
    stages: list[CompetitionStage] | None
    """Stages for composite formats (group_then_knockout, multi_stage_qualifier).
    None or empty for simple formats."""

    # Lifecycle (Reference-plane standard)
    first_season: int | None
    """Year of first edition, or None if ongoing/new."""

    active: bool
    """True if the competition is currently active (accepting fixtures)."""

    successor_competition_id: str | None
    """If this competition was renamed/replaced, points to the new one (e.g., UEFA Cup → UEFA Europa League)."""
