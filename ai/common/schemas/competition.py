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


# Phase 19 §19.5 — International tournament support types


class ConfoederationGroup(TypedDict, total=False):
    """A confederation group within a multi-round WC qualifier (e.g. UEFA Group A).
    
    Per ROADMAP §19.5 ledger #8, WC qualifiers use confederation-specific groups
    with carry-forward rules and automatic qualifier slots.
    """

    size: int
    """Team count in the group, e.g. 10 for CONMEBOL."""

    carry_forward_rules: list[str]
    """Rules for points/advancement carry-over between qualifying rounds."""

    automatic_qualifier_slots: int
    """Teams automatically qualified from this group to inter-confederation play-offs."""

    playoff_slots: int
    """Teams competing in inter-confederation play-offs."""


class InterConfederationPath(TypedDict, total=False):
    """Pathway from one confederation to another in multi-confederation qualifiers.
    
    Example: the inter-confederation play-offs between UEFA and CONMEBOL teams
    in a hypothetical World Cup expansion format.
    """

    from_confederation: str
    """Source confederation, e.g. 'UEFA'."""

    to_confederation: str
    """Target confederation, e.g. 'CONMEBOL'."""

    slot_count: int
    """How many slots are contested on this path."""

    format: Literal["single_leg", "two_leg"]
    """Single-elimination or aggregate-score format."""


class QualificationRound(TypedDict, total=False):
    """A round within a multi-round WC or continental qualifier.
    
    Example: UEFA group stage → UEFA two-leg play-offs → inter-confederation play-offs.
    """

    round_id: str
    """Unique identifier within the tournament, e.g. 'group_stage', 'playoff_round_1'."""

    format: Literal["group_stage", "two_leg_tie", "single_leg"]
    """Format of this round."""

    teams_in: int
    """Teams entering this round."""

    teams_advance: int
    """Teams advancing to the next round."""


class GroupStageConfig(TypedDict, total=False):
    """Configuration for group stage in continental championships and tournaments."""

    group_count: int
    """Number of groups, e.g. 4 for Euro, 8 for AFCON."""

    teams_per_group: int
    """Teams in each group."""

    teams_advance_per_group: int
    """Teams advancing from each group."""

    tiebreaker_rules: list[str]
    """Confederation-specific tiebreaker order (e.g. ['points', 'goals_for', 'head_to_head'])."""


class KnockoutPhaseConfig(TypedDict, total=False):
    """Configuration for knockout phases in tournaments."""

    teams_in: int
    """Teams entering the knockout phase."""

    format: Literal["round_of_16", "round_of_8", "semifinal"]
    """Bracket size."""

    away_goals_rule: bool
    """Whether away-goals rule applies (Euro/Copa América etc.)."""


class TournamentTiebreakerRules(TypedDict, total=False):
    """Tournament-specific tiebreaker rules (separate from domestic league rules)."""

    group_stage_rules: list[str]
    """Order of application in group stage (e.g. points, goals for, head-to-head)."""

    knockout_extra_time: bool
    """Whether extra time is used in knockout rounds."""

    knockout_penalties: bool
    """Whether penalties are used if extra time inconclusive."""


class WcQualifierFormat(TypedDict, total=False):
    """WC qualifier format configuration (Phase 19 §19.5)."""

    confederation_groups: list[ConfoederationGroup]
    """Groups per confederation in the qualifier."""

    inter_confederation_paths: list[InterConfederationPath]
    """Pathways between confederations."""

    rounds: list[QualificationRound]
    """Multi-round structure (group stage, play-offs, inter-confederation, etc.)."""

    participant_count_range: dict
    """Min/max team count (e.g. {min: 190, max: 210})."""

    qualification_matrix_schema_version: int
    """Version flag for detecting mid-edition rule changes."""


class ContinentalChampionshipFormat(TypedDict, total=False):
    """Continental championship format (Euro, Copa América, AFCON, etc.)."""

    group_stage: GroupStageConfig | None
    """Group stage configuration, or None for direct knockout."""

    knockout_phase: KnockoutPhaseConfig | None
    """Knockout phase, or None if group-stage-only."""

    tiebreaker_rules: TournamentTiebreakerRules
    """Tournament-specific tiebreaker rules."""

    host_nation_flag: bool
    """True if this tournament has a designated host nation (affects home-advantage)."""


class ParticipantCrystallisationGate(TypedDict, total=False):
    """Gate for crystallising participant rosters in multi-stage tournaments.
    
    Phase 19 §19.5 ledger #14 — Participant rosters must be crystallised at
    known points in the tournament (e.g., end of group stage) to enable
    downstream systems to rely on stable team lists.
    """

    crystallisation_timestamp_utc: str
    """ISO-8601 timestamp when the roster becomes final."""

    teams_confirmed: int
    """Number of teams confirmed to advance."""

    locked: bool
    """True if roster is now immutable for downstream systems."""

    reason: str
    """Reason for crystallisation (e.g., 'group_stage_complete', 'ko_draw_done')."""

