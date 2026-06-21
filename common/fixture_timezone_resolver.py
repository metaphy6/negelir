"""Phase 19 §19.19 — Fixture lifecycle: timezone & deduplication.

Handles:
- UTC normalization at ingest time
- Timezone resolver for (league_id, source) pairs
- Cross-source fixture deduplication
- Fixture postponement/cancellation signals
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
import pytz


@dataclass
class FixtureTimezone:
    """Maps (league_id, source) to IANA timezone."""
    league_id: str
    source: str
    timezone_str: str
    
    def resolve(self) -> pytz.tzinfo:
        """Return pytz timezone object."""
        try:
            return pytz.timezone(self.timezone_str)
        except Exception:
            raise ValueError(f"Invalid timezone: {self.timezone_str}")


@dataclass
class FixtureRecord:
    """Schedule-plane fixture record with timezone handling."""
    
    league_id: str
    source: str
    home_canonical_id: str
    away_canonical_id: str
    kickoff_utc: datetime  # Canonical: all comparisons use this
    kickoff_local: Tuple[str, str]  # (time_str, tz_str) for source debug
    status: str = "scheduled"  # scheduled, postponed, cancelled, abandoned
    secondary_source_data: Optional[Dict] = None  # Added on cross-source merge
    
    def __post_init__(self):
        """Validate fixture record."""
        if self.kickoff_utc.tzinfo != pytz.UTC:
            raise ValueError("kickoff_utc must be in UTC")
        if self.status not in ["scheduled", "postponed", "cancelled", "abandoned"]:
            raise ValueError(f"Invalid status: {self.status}")
    
    def get_dedup_key(self) -> Tuple:
        """Get deduplication key: (league_id, home, away, kickoff_utc_rounded)."""
        # Round kickoff_utc to nearest 2-minute boundary for dedup window
        rounded = self.kickoff_utc.replace(second=0, microsecond=0)
        if rounded.minute % 2 == 1:
            rounded = rounded.replace(minute=rounded.minute + 1)
        return (self.league_id, self.home_canonical_id, self.away_canonical_id, rounded)


class FixtureDeduplicator:
    """Cross-source fixture deduplication."""
    
    def __init__(self, cfg):
        self.cfg = cfg
        self.dedup_window_minutes = cfg.fixture_dedup_window_minutes  # default 120
        self.quarantine_hours = cfg.fixture_dedup_quarantine_hours  # default 6
        self.existing_fixtures: Dict[Tuple, FixtureRecord] = {}
        self.quarantine_bin: Dict[str, FixtureRecord] = {}
    
    def try_merge_or_quarantine(self, new_fixture: FixtureRecord) -> Tuple[bool, str]:
        """
        Try to merge new fixture with existing record within dedup window.
        Returns: (merged, action)
          - merged=True, action="merged": merged into existing record
          - merged=False, action="quarantined": held in quarantine
          - merged=False, action="stored": stored as new record
        """
        key = new_fixture.get_dedup_key()
        dedup_window = timedelta(minutes=self.dedup_window_minutes)
        
        # Search for matching fixture within dedup window
        for stored_key, stored_fixture in self.existing_fixtures.items():
            if self._keys_match_within_window(key, stored_key, dedup_window):
                # Found match: merge
                if stored_fixture.secondary_source_data is None:
                    stored_fixture.secondary_source_data = {}
                stored_fixture.secondary_source_data[new_fixture.source] = {
                    'kickoff_local': new_fixture.kickoff_local,
                    'status': new_fixture.status
                }
                return (True, "merged")
        
        # No match found: quarantine or store
        quarantine_key = f"{new_fixture.league_id}:{new_fixture.home_canonical_id}:{new_fixture.away_canonical_id}"
        if quarantine_key not in self.quarantine_bin:
            self.quarantine_bin[quarantine_key] = new_fixture
            return (False, "quarantined")
        
        # Already in quarantine: store as new record
        self.existing_fixtures[key] = new_fixture
        return (False, "stored")
    
    def _keys_match_within_window(self, key1: Tuple, key2: Tuple, window: timedelta) -> bool:
        """Check if two dedup keys match within time window."""
        if key1[:3] != key2[:3]:  # league_id, home, away don't match
            return False
        
        # Check time window
        time1 = key1[3]
        time2 = key2[3]
        return abs((time1 - time2).total_seconds()) <= window.total_seconds()


class FixtureTimezoneNormalizer:
    """Convert local times to UTC."""
    
    def __init__(self, cfg):
        self.cfg = cfg
        self.resolvers: Dict[str, Dict[str, str]] = {}  # league_id -> {source -> tz_str}
    
    def normalize_to_utc(
        self,
        league_id: str,
        source: str,
        kickoff_local_str: str,
        explicit_offset: Optional[str] = None
    ) -> Tuple[datetime, Tuple[str, str]]:
        """
        Convert local kickoff to UTC.
        
        Args:
            kickoff_local_str: e.g. "19:30"
            explicit_offset: optional offset from source, e.g. "+03:00"
        
        Returns:
            (kickoff_utc, kickoff_local_tuple)
        """
        # Use explicit offset if provided
        if explicit_offset:
            tz = timezone(timedelta(seconds=self._parse_offset(explicit_offset)))
        else:
            # Resolve timezone from registry
            tz_str = self.resolvers.get(league_id, {}).get(source)
            if not tz_str:
                raise ValueError(f"No timezone for {league_id} / {source}")
            tz = pytz.timezone(tz_str)
        
        # Parse local time (assuming today's date)
        today = datetime.now(pytz.UTC).date()
        local_dt = datetime.strptime(f"{today} {kickoff_local_str}", "%Y-%m-%d %H:%M")
        
        # Apply timezone
        if isinstance(tz, pytz.tzinfo.BaseTzInfo):
            local_dt = tz.localize(local_dt)
        else:
            local_dt = local_dt.replace(tzinfo=tz)
        
        # Convert to UTC
        utc_dt = local_dt.astimezone(pytz.UTC)
        
        return (utc_dt, (kickoff_local_str, tz_str if not explicit_offset else explicit_offset))
    
    def _parse_offset(self, offset_str: str) -> int:
        """Parse offset string like '+03:00' to seconds."""
        sign = 1 if offset_str[0] == '+' else -1
        hours, minutes = offset_str[1:].split(':')
        return sign * (int(hours) * 3600 + int(minutes) * 60)
    
    def register_timezone(self, league_id: str, source: str, tz_str: str) -> None:
        """Register timezone for (league_id, source) pair."""
        if league_id not in self.resolvers:
            self.resolvers[league_id] = {}
        self.resolvers[league_id][source] = tz_str
