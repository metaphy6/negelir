"""Phase 19 §19.17 — API catalog surface models.

Provides paginated catalog listing and filtering models.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum


class LeagueTier(str, Enum):
    """League tier classification."""
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class LeagueStatus(str, Enum):
    """League operational status."""
    ACTIVE = "active"
    BETA = "beta"
    RESEARCH = "research"
    DECOMMISSIONED = "decommissioned"


@dataclass
class LeagueReadinessScore:
    """Readiness metrics for a league (admin only)."""
    league_id: str
    overall_score: float  # 0-100
    coverage_score: float  # 0-100
    timeliness_score: float  # 0-100
    accuracy_score: float  # 0-100
    team_coverage_pct: float
    fixture_freshness_hours: int


@dataclass
class LeagueCatalogEntry:
    """Single league entry in catalog listing."""
    league_id: str
    name_en: str
    name_tr: str
    confederation: str
    tier: LeagueTier
    status: LeagueStatus
    sources_count: int
    last_fixture_date_utc: Optional[str] = None
    readiness_score: Optional[LeagueReadinessScore] = None  # Admin only


@dataclass
class CatalogListResponse:
    """Paginated catalog listing response."""
    leagues: List[LeagueCatalogEntry] = field(default_factory=list)
    total_count: int = 0
    next_cursor: Optional[str] = None
    has_more: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            'leagues': [
                {
                    'league_id': l.league_id,
                    'name_en': l.name_en,
                    'name_tr': l.name_tr,
                    'confederation': l.confederation,
                    'tier': l.tier.value,
                    'status': l.status.value,
                    'sources_count': l.sources_count,
                    'last_fixture_date_utc': l.last_fixture_date_utc,
                    'readiness_score': l.readiness_score.__dict__ if l.readiness_score else None
                }
                for l in self.leagues
            ],
            'total_count': self.total_count,
            'next_cursor': self.next_cursor,
            'has_more': self.has_more
        }


@dataclass
class CatalogListRequest:
    """Pagination and filtering request."""
    after: Optional[str] = None  # Cursor for pagination
    limit: int = 50  # Default page size
    tier: Optional[LeagueTier] = None  # Filter by tier
    confederation: Optional[str] = None  # Filter by confederation
    status: Optional[LeagueStatus] = None  # Filter by status
    text: Optional[str] = None  # Free-text search on name_en/name_tr
    include_readiness: bool = False  # Include readiness score (admin only)
    
    def validate(self, max_limit: int = 50) -> tuple[bool, str]:
        """Validate request parameters."""
        if self.limit < 1 or self.limit > max_limit:
            return False, f"limit must be between 1 and {max_limit}"
        return True, ""
