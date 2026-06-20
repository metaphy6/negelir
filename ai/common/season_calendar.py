"""Phase 19 §19.14 — Season calendar & fixture calendar ingestion.

Models:
- SeasonCalendar: tracks season boundaries, split seasons
- Fixture timezone handling
- Freshness window computation
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, Tuple, Dict
import pytz


@dataclass
class SeasonCalendar:
    """Represents a league's season boundaries and fixtures."""
    
    league_id: str
    season: str  # e.g. "2024-2025"
    start_date: date
    end_date: date
    primary_timezone: str  # IANA timezone, e.g. "Europe/Istanbul"
    is_split_season: bool = False
    split_break_start: Optional[date] = None
    split_break_end: Optional[date] = None
    
    def __post_init__(self):
        """Validate season calendar constraints."""
        if self.end_date <= self.start_date:
            raise ValueError(f"end_date {self.end_date} must be after start_date {self.start_date}")
        if self.is_split_season and (not self.split_break_start or not self.split_break_end):
            raise ValueError("split_season requires split_break_start and split_break_end")
    
    def contains_date(self, target_date: date) -> bool:
        """Check if a date falls within this season."""
        if self.start_date <= target_date <= self.end_date:
            # Exclude split break period if applicable
            if self.is_split_season:
                if self.split_break_start <= target_date <= self.split_break_end:
                    return False
            return True
        return False
    
    def get_timezone(self) -> pytz.tzinfo:
        """Return pytz timezone object for this league."""
        try:
            return pytz.timezone(self.primary_timezone)
        except Exception:
            raise ValueError(f"Invalid timezone: {self.primary_timezone}")
    
    def compute_freshness_window_days(self) -> int:
        """Compute freshness window based on season boundaries."""
        # For active leagues: refresh within 24h of fixtures
        # For off-season: refresh weekly
        now = datetime.now(pytz.UTC).date()
        if self.contains_date(now):
            return 1  # In-season: 1 day freshness
        else:
            return 7  # Off-season: 1 week freshness
    
    def get_retrain_trigger_dates(self) -> Tuple[date, date]:
        """Compute optimal retrain dates based on season."""
        # Retrain near start and middle of season
        start = self.start_date
        end = self.end_date
        mid = start + (end - start) // 2
        return (start, mid)


class SeasonCalendarRegistry:
    """Registry of all league seasons."""
    
    def __init__(self):
        self.calendars: Dict[str, SeasonCalendar] = {}
    
    def register(self, calendar: SeasonCalendar) -> None:
        """Register a season calendar."""
        key = f"{calendar.league_id}:{calendar.season}"
        if key in self.calendars:
            raise ValueError(f"Season already registered: {key}")
        self.calendars[key] = calendar
    
    def get_current_season(self, league_id: str) -> Optional[SeasonCalendar]:
        """Get current season for a league."""
        now = datetime.now().date()
        for calendar in self.calendars.values():
            if calendar.league_id == league_id and calendar.contains_date(now):
                return calendar
        return None
    
    def validate_all_have_calendars(self, league_ids: list) -> Tuple[bool, list]:
        """Check that all leagues have a season calendar registered."""
        missing = []
        for league_id in league_ids:
            if not self.get_current_season(league_id):
                missing.append(league_id)
        return len(missing) == 0, missing
