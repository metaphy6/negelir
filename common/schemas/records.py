"""TypedDict definitions for feed record types (Phase 16.3, bullet 7).

Maps to JSON schemas in feeds/*.v1.json and supports
three-way consistency validation (TypedDict ↔ JSONSchema ↔ pyarrow).
"""

from typing import Any, TypedDict, Optional, List, Literal


class ScoreHome(TypedDict):
    """Home team score record."""
    team_id: str
    score: int
    name: Optional[str]


class ScoreAway(TypedDict):
    """Away team score record."""
    team_id: str
    score: int
    name: Optional[str]


class Score(TypedDict):
    """Score Payload (v1) — Live-plane entity."""
    match_stable_id: str
    minute: int
    status: str  # not_started, live, halftime, finished, abandoned
    home: ScoreHome
    away: ScoreAway
    possession_team_id: Optional[str]
    last_event_at: Optional[str]


class ScheduleTeam(TypedDict):
    """Team record in schedule."""
    team_id: str
    team_name: Optional[str]


class Schedule(TypedDict):
    """Schedule Payload (v1) — Static match metadata."""
    match_stable_id: str
    kickoff_utc: str
    home: ScheduleTeam
    away: ScheduleTeam
    competition: str
    status: str  # scheduled, postponed, cancelled, finished
    referee: Optional[str]
    venue: Optional[str]


class MarketOdds(TypedDict):
    """Market odds."""
    home: Optional[float]
    draw: Optional[float]
    away: Optional[float]


class Market(TypedDict):
    """Market Payload (v1) — Odds and lines."""
    match_stable_id: str
    market_name: str
    updated_at: str
    odds: Optional[MarketOdds]
    spread: Optional[float]
    total_lines: Optional[int]


class LineupPlayer(TypedDict):
    """Lineup player entry."""
    player_id: str
    position: str
    number: int
    name: Optional[str]


class Lineup(TypedDict):
    """Lineup Payload (v1) — Confirmed team lineups."""
    match_stable_id: str
    team_id: str
    confirmed_at: str
    players: List[LineupPlayer]


class TbdOpponentFixture(TypedDict, total=False):
    """Phase 19.5 — TBD-opponent placeholder fixture (WC qualifier play-offs).
    
    When WC playoff opponents are not yet resolved (e.g., waiting for a 
    second-leg result or inter-confederation bracket draw), fixtures use
    this type with a degenerate prediction (home_win_prob: null).
    """
    
    match_stable_id: str
    """Stable ID for this fixture."""
    
    kickoff_utc: str
    """Scheduled kickoff time in UTC ISO-8601 format."""
    
    home: ScheduleTeam
    """Home team (known)."""
    
    away: ScheduleTeam
    """Away team (may have team_id='TBD', team_name=None)."""
    
    competition: str
    """Competition, e.g., 'wc_qualifier_playoff'."""
    
    status: str
    """Fixture status, e.g., 'tbd_opponent', 'scheduled', 'finished'."""
    
    tbd_reason: str
    """Reason opponent is TBD, e.g., 'play_off_not_drawn', 'qualifier_leg_pending'."""
    
    expected_confirmation_at: Optional[str]
    """Expected time when opponent will be confirmed, or None if unknown."""
    
    referee: Optional[str]
    """Referee name (optional)."""
    
    venue: Optional[str]
    """Venue name (optional)."""


# Feed record type registry (used by schema generator)
RECORD_TYPES = {
    "score": Score,
    "schedule": Schedule,
    "market": Market,
    "lineup": Lineup,
}

# Phase 21 — Enrichment planes

class TransferPayload(TypedDict):
    """Transfer Payload (v1) — Roster-state plane (Phase 21.1).
    
    Represents a player transfer between clubs.
    """
    transfer_id: str
    """Source-native ID; canonicalized."""
    
    player_id: str
    """FK to Reference plane."""
    
    from_team_id: Optional[str]
    """Null = first pro contract."""
    
    to_team_id: Optional[str]
    """Null = retirement / released."""
    
    transfer_window: Literal["summer", "winter", "emergency"]
    """Transfer window classification."""
    
    transfer_type: Literal["permanent", "loan", "loan_with_option", "free", "end_of_loan"]
    """Type of transfer."""
    
    fee_eur: Optional[int]
    """Null when undisclosed."""
    
    contract_until: Optional[str]
    """ISO date."""
    
    announced_at: str
    """ISO-8601 UTC."""
    
    effective_at: str
    """ISO-8601 UTC; can equal announced_at."""
    
    confidence: Literal["rumour", "agreed", "official"]
    """Editorial provenance."""


class ContractPayload(TypedDict):
    """Contract Payload (v1) — Roster-state plane (Phase 21.1).
    
    Represents a contract between a player and team.
    """
    contract_id: str
    """Unique contract identifier."""
    
    player_id: str
    """FK to Reference plane."""
    
    team_id: str
    """FK to Reference plane."""
    
    starts_at: str
    """ISO date."""
    
    expires_at: str
    """ISO date."""
    
    extension: bool
    """True if this updates an existing contract."""


class SuspensionPayload(TypedDict):
    """Suspension Payload (v1) — Roster-state plane (Phase 21.1).
    
    Represents a player suspension.
    """
    suspension_id: str
    """Unique suspension identifier."""
    
    player_id: str
    """FK to Reference plane."""
    
    team_id: str
    """FK to Reference plane."""
    
    competition_id: str
    """Suspensions are competition-scoped."""
    
    reason: Literal["accumulated_yellows", "red", "disciplinary", "doping"]
    """Reason for suspension."""
    
    matches_remaining: int
    """Number of matches the suspension covers."""
    
    starts_at: str
    """ISO date."""
    
    expires_after_match_id: Optional[str]
    """Match ID after which suspension expires, or None if indefinite."""


class InjuryPayload(TypedDict):
    """Injury Payload (v1) — Health plane (Phase 21.2).
    
    Represents a player injury or recovery status.
    """
    injury_id: str
    """Unique injury identifier."""
    
    player_id: str
    """FK to Reference plane."""
    
    team_id: str
    """FK to Reference plane."""
    
    body_part: str
    """Taxonomy in lexicon/injury_body_parts.yaml; e.g., 'knee', 'ankle', 'hamstring'."""
    
    severity: Literal["minor", "moderate", "major", "season_ending", "career_threat"]
    """Injury severity level."""
    
    diagnosed_at: str
    """ISO-8601 UTC when injury was diagnosed."""
    
    expected_return: Optional[str]
    """ISO date when player is expected to return; None if unknown."""
    
    confidence: Literal["club_statement", "press", "rumour"]
    """Source confidence level."""
    
    source_url_hash: str
    """SHA-256(canonical_url.encode('utf-8')).hexdigest(); provenance without storing raw URL."""


class AvailabilityPayload(TypedDict):
    """Availability Payload (v1) — Health plane (Phase 21.2).
    
    Represents a player's availability status for a fixture or general period.
    """
    availability_id: str
    """Unique availability identifier."""
    
    player_id: str
    """FK to Reference plane."""
    
    team_id: str
    """FK to Reference plane."""
    
    fixture_id: Optional[str]
    """None = general availability; set = per-fixture status."""
    
    status: Literal["fit", "doubtful", "out", "suspended", "international_duty", "rest"]
    """Availability status."""
    
    asserted_at: str
    """ISO-8601 UTC when this status was asserted."""
    
    source_confidence: Literal["club_official", "manager_presser", "press", "rumour"]
    """Source confidence level."""


# Phase 21.3 — Officials plane

class RefereeRollingStats(TypedDict):
    """Rolling stats for a referee (sub-dict of RefereeProfilePayload).
    
    Populated exclusively by the rolling-stats reactor on match-finalize events.
    Never written by the extractor.
    """
    matches_officiated_total: int
    """Cumulative matches officiated by this referee."""
    
    matches_officiated_window: int
    """Matches officiated within cfg.enrichment_referee_window_matches (default 50)."""
    
    yellows_per_match: float
    """Average yellow cards per match (window-based)."""
    
    reds_per_match: float
    """Average red cards per match (window-based)."""
    
    penalties_per_match: float
    """Average penalties per match (window-based)."""
    
    home_win_pct: float
    """Percentage of home-team wins in matches officiated by this referee (0.0–1.0)."""
    
    avg_added_time_min: float
    """Average added time in minutes (window-based)."""


class RefereeAssignmentPayload(TypedDict):
    """RefereeAssignment Payload (v1) — Officials plane (Phase 21.3).
    
    Represents referee assignment for a fixture.
    """
    assignment_id: str
    """Unique assignment identifier."""
    
    fixture_id: str
    """FK to Schedule plane fixture."""
    
    main_referee_id: str
    """FK to RefereeProfilePayload; validated by extractor."""
    
    assistant_referee_ids: List[str]
    """List of assistant referee IDs."""
    
    fourth_official_id: Optional[str]
    """Fourth official ID, if present."""
    
    var_referee_id: Optional[str]
    """VAR referee ID, if present."""
    
    avar_referee_id: Optional[str]
    """Assistant VAR referee ID, if present."""
    
    announced_at: str
    """ISO-8601 UTC when assignment was announced."""
    
    last_minute_change: bool
    """True if reassigned within 24h pre-KO; used to invalidate derived features."""


class RefereeProfilePayload(TypedDict):
    """RefereeProfile Payload (v1) — Officials plane (Phase 21.3).
    
    Represents a referee and their rolling statistics.
    """
    referee_id: str
    """Unique referee identifier."""
    
    full_name: str
    """Referee's full name."""
    
    nationality: str
    """ISO-3166 country code (e.g., 'TR', 'EN')."""
    
    federation: str
    """Federation code (e.g., 'TFF', 'FA', 'UEFA', 'FIFA')."""
    
    licence_level: Literal["fifa", "uefa_elite", "uefa_first", "domestic_top", "domestic"]
    """Referee licence level."""
    
    debut_year: int
    """Year of debut in professional refereeing."""
    
    rolling_stats: RefereeRollingStats
    """Rolling statistics, updated by reactor on match finalize; never by extractor."""



class WeatherForecastPayload(TypedDict):
    """WeatherForecast Payload (v1) — Environment plane (Phase 21.4).
    
    Hourly weather forecast with 24-48h horizon for a venue.
    Per ENRICHMENT_DATA.md §5.1.
    """
    forecast_id: str
    """Unique forecast identifier."""
    
    venue_id: str
    """Venue/stadium identifier from Reference plane."""
    
    valid_at: str
    """ISO-8601 UTC: the forecast's target time."""
    
    issued_at: str
    """ISO-8601 UTC: when the forecast was issued."""
    
    horizon_hours: int
    """Hours between issued_at and valid_at."""
    
    temp_c: float
    """Temperature in Celsius."""
    
    wind_kph: float
    """Wind speed in kilometres per hour."""
    
    wind_direction_deg: int
    """Wind direction in degrees (0-359)."""
    
    precip_mm_per_hr: float
    """Precipitation (rain/snow) in millimetres per hour."""
    
    humidity_pct: int
    """Relative humidity as percentage (0-100)."""
    
    visibility_km: Optional[float]
    """Visibility in kilometres (null if unavailable)."""
    
    conditions: str
    """Canonical weather condition: clear, rain, snow, fog, thunderstorm."""


class WeatherActualPayload(TypedDict):
    """WeatherActual Payload (v1) — Environment plane (Phase 21.4).
    
    Observed weather conditions at KO and post-match.
    Overrides forecasts for post-KO computations.
    """
    actual_id: str
    """Unique actual observation identifier."""
    
    venue_id: str
    """Venue/stadium identifier from Reference plane."""
    
    observed_at: str
    """ISO-8601 UTC: observation timestamp (KO ±15 min or post-match)."""
    
    temp_c: float
    """Temperature in Celsius at observation time."""
    
    wind_kph: float
    """Wind speed in kilometres per hour."""
    
    wind_direction_deg: int
    """Wind direction in degrees (0-359)."""
    
    precip_mm_per_hr: float
    """Precipitation in millimetres per hour."""
    
    humidity_pct: int
    """Relative humidity as percentage (0-100)."""
    
    visibility_km: Optional[float]
    """Visibility in kilometres (null if unavailable)."""
    
    conditions: str
    """Canonical weather condition: clear, rain, snow, fog, thunderstorm."""


class PitchConditionPayload(TypedDict):
    """PitchCondition Payload (v1) — Environment plane (Phase 21.4).
    
    Pitch inspection record; default condition is 'good' if no record exists
    in the past 7 days (see ENRICHMENT_DATA.md §5).
    """
    pitch_id: str
    """Unique pitch/venue identifier."""
    
    venue_id: str
    """Venue/stadium identifier from Reference plane (duplicates pitch_id for now)."""
    
    surface: Literal["natural_grass", "hybrid", "artificial_turf", "indoor"]
    """Playing surface type."""
    
    condition: Literal["pristine", "good", "worn", "muddy", "frozen", "playable_with_concerns"]
    """Pitch condition classification."""
    
    last_match_at: Optional[str]
    """ISO-8601 UTC: timestamp of the last match played on this pitch (if known)."""
    
    inspection_at: str
    """ISO-8601 UTC: when this condition was inspected."""


# Complete feed record type registry (14 types: 4 base + 10 enrichment)
RECORD_TYPES = {
    # Base planes (Phases 12-16)
    "score": Score,
    "schedule": Schedule,
    "market": Market,
    "lineup": Lineup,
    # Enrichment planes (Phase 21)
    "transfer": TransferPayload,
    "contract": ContractPayload,
    "suspension": SuspensionPayload,
    "injury": InjuryPayload,
    "availability": AvailabilityPayload,
    "referee_assignment": RefereeAssignmentPayload,
    "referee_profile": RefereeProfilePayload,
    "weather_forecast": WeatherForecastPayload,
    "weather_actual": WeatherActualPayload,
    "pitch_condition": PitchConditionPayload,
}
