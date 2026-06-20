"""TypedDict definitions for feed record types (Phase 16.3, bullet 7).

Maps to JSON schemas in feeds/*.v1.json and supports
three-way consistency validation (TypedDict ↔ JSONSchema ↔ pyarrow).
"""

from typing import Any, TypedDict, Optional, List


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
