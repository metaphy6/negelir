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


# Feed record type registry (used by schema generator)
RECORD_TYPES = {
    "score": Score,
    "schedule": Schedule,
    "market": Market,
    "lineup": Lineup,
}
