"""Phase 21.5 — Derived views (idempotent reactors — no new tables).

Computed views over the four enrichment planes (Roster, Health, Officials, Environment)
plus the existing Market, Schedule, and Live planes. No new TypedDicts — all outputs
are computed on-demand from existing plane records.

Idempotent: identical inputs → identical outputs.
Coalesced: events batched over cfg.enrichment_derived_view_coalesce_ms window.

Binding per ROADMAP §21.5 and ENRICHMENT_DATA.md §6.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

from ai.common.config import cfg
from ai.common.logger import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Bullet 2: Market-Movement View
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class MarketMovementView:
    """Market-movement derived view: implied probability shifts for 1x2 markets.
    
    Fires on Market plane record insert; keyed by (fixture_id, market_type).
    Computed from opening (24h before KO) and closing (at KO) odds.
    """
    fixture_id: str
    market_type: str = "1x2"  # Only 1x2 for now
    
    drift_1x2_home_pct: float = 0.0
    drift_1x2_draw_pct: float = 0.0
    drift_1x2_away_pct: float = 0.0
    drift_total_pct: float = 0.0
    implied_prob_shift_max: float = 0.0
    high_drift_flag: bool = False


def compute_market_movement(
    market_records: list[dict],
    fixture_id: str,
    fixture_kickoff_utc: str,
    cfg_obj=None,
) -> MarketMovementView:
    """Compute market-movement view from market records.
    
    Args:
        market_records: List of market records (sorted by timestamp)
        fixture_id: The fixture ID
        fixture_kickoff_utc: ISO-8601 fixture kickoff time
        cfg_obj: Config object (default: use global cfg)
        
    Returns:
        MarketMovementView with drift indicators
    """
    if cfg_obj is None:
        cfg_obj = cfg
    
    view = MarketMovementView(fixture_id=fixture_id)
    
    if not market_records:
        return view
    
    # Find opening (earliest within 24h before KO)
    try:
        ko_time = datetime.fromisoformat(fixture_kickoff_utc.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return view
    
    window_start = ko_time - timedelta(hours=24)
    opening = None
    closing = None
    
    for rec in market_records:
        try:
            rec_time = datetime.fromisoformat(rec.get('timestamp', '').replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        
        if window_start <= rec_time <= ko_time:
            if opening is None:
                opening = rec
            closing = rec
    
    if not opening or not closing:
        return view
    
    # Extract implied probabilities
    opening_h = opening.get('implied_prob_home', 0.0) or 0.0
    opening_d = opening.get('implied_prob_draw', 0.0) or 0.0
    opening_a = opening.get('implied_prob_away', 0.0) or 0.0
    
    closing_h = closing.get('implied_prob_home', 0.0) or 0.0
    closing_d = closing.get('implied_prob_draw', 0.0) or 0.0
    closing_a = closing.get('implied_prob_away', 0.0) or 0.0
    
    # Compute percentage changes
    def pct_change(old_val: float, new_val: float) -> float:
        if old_val == 0.0:
            return 0.0
        return ((new_val - old_val) / old_val) * 100.0
    
    view.drift_1x2_home_pct = pct_change(opening_h, closing_h)
    view.drift_1x2_draw_pct = pct_change(opening_d, closing_d)
    view.drift_1x2_away_pct = pct_change(opening_a, closing_a)
    view.drift_total_pct = abs(view.drift_1x2_home_pct) + abs(view.drift_1x2_draw_pct) + abs(view.drift_1x2_away_pct)
    
    view.implied_prob_shift_max = max(
        abs(view.drift_1x2_home_pct),
        abs(view.drift_1x2_draw_pct),
        abs(view.drift_1x2_away_pct),
    )
    
    view.high_drift_flag = view.implied_prob_shift_max > cfg_obj.enrichment_drift_high_threshold
    
    return view


# ═══════════════════════════════════════════════════════════════════════════
# Bullet 3: Fixture-Congestion View
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FixtureCongestionView:
    """Fixture-congestion derived view: team load and travel metrics.
    
    Fires on Schedule plane record insert.
    Refines existing v0.2 columns using real Schedule + Live plane data.
    """
    fixture_id: str
    home_team_id: str
    away_team_id: str
    
    home_fixture_congestion_7d: int = 0
    away_fixture_congestion_7d: int = 0
    home_fixture_congestion_14d: int = 0
    away_fixture_congestion_14d: int = 0
    home_travel_km_7d: float = 0.0
    away_travel_km_7d: float = 0.0
    congestion_diff_7d: int = 0
    is_post_international_break: float = 0.0  # 0.0=neither, 0.5=one, 1.0=both


def compute_fixture_congestion(
    fixture_id: str,
    home_team_id: str,
    away_team_id: str,
    fixture_kickoff_utc: str,
    schedule_records: list[dict],
    venue_coords: dict,  # {venue_id: (lat, lon)}
    international_breaks: list[dict],
    cfg_obj=None,
) -> FixtureCongestionView:
    """Compute fixture-congestion view from schedule data.
    
    Args:
        fixture_id: The fixture ID
        home_team_id: Home team ID
        away_team_id: Away team ID
        fixture_kickoff_utc: ISO-8601 fixture kickoff time
        schedule_records: All schedule records for both teams
        venue_coords: Dict mapping venue_id → (lat, lon)
        international_breaks: List of international break windows
        cfg_obj: Config object
        
    Returns:
        FixtureCongestionView with congestion and travel metrics
    """
    if cfg_obj is None:
        cfg_obj = cfg
    
    view = FixtureCongestionView(
        fixture_id=fixture_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )
    
    try:
        ko_time = datetime.fromisoformat(fixture_kickoff_utc.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return view
    
    # Count matches in 7d and 14d windows
    window_7d_start = ko_time - timedelta(days=7)
    window_14d_start = ko_time - timedelta(days=14)
    
    def count_team_matches(team_id: str, window_start: datetime) -> tuple[int, int]:
        """Count matches for team in 7d and 14d windows. Returns (7d_count, 14d_count)."""
        count_7d = 0
        count_14d = 0
        for rec in schedule_records:
            if rec.get('home_team_id') == team_id or rec.get('away_team_id') == team_id:
                try:
                    match_time = datetime.fromisoformat(rec.get('kickoff_utc', '').replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    continue
                
                if window_start <= match_time < ko_time:
                    if match_time >= window_7d_start:
                        count_7d += 1
                    count_14d += 1
        
        return count_7d, count_14d
    
    h_7d, h_14d = count_team_matches(home_team_id, window_14d_start)
    a_7d, a_14d = count_team_matches(away_team_id, window_14d_start)
    
    view.home_fixture_congestion_7d = h_7d
    view.away_fixture_congestion_7d = a_7d
    view.home_fixture_congestion_14d = h_14d
    view.away_fixture_congestion_14d = a_14d
    view.congestion_diff_7d = h_7d - a_7d  # positive = home more congested
    
    # Compute travel km (sum of distances in last 3 matches within 7d)
    def compute_travel_km(team_id: str) -> float:
        """Sum distance between venues for team's last 3 matches in 7d window."""
        matches = []
        window_7d_start = ko_time - timedelta(days=7)
        for rec in schedule_records:
            if (rec.get('home_team_id') == team_id or rec.get('away_team_id') == team_id):
                try:
                    match_time = datetime.fromisoformat(rec.get('kickoff_utc', '').replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    continue
                
                if window_7d_start <= match_time < ko_time:
                    venue_id = rec.get('home_venue_id') if rec.get('home_team_id') == team_id else rec.get('away_venue_id')
                    matches.append((match_time, venue_id, rec.get('home_lat'), rec.get('home_lon'), rec.get('away_lat'), rec.get('away_lon')))
        
        matches.sort()  # Sort by time
        
        total_km = 0.0
        for i in range(1, min(4, len(matches))):  # Last 3 matches
            prev_match = matches[i-1]
            curr_match = matches[i]
            
            # Get venue coordinates
            prev_venue_id = prev_match[1]
            curr_venue_id = curr_match[1]
            
            prev_coords = venue_coords.get(prev_venue_id)
            curr_coords = venue_coords.get(curr_venue_id)
            
            if prev_coords and curr_coords:
                dist_km = _haversine_distance(prev_coords[0], prev_coords[1], curr_coords[0], curr_coords[1])
                total_km += dist_km
        
        return total_km
    
    view.home_travel_km_7d = compute_travel_km(home_team_id)
    view.away_travel_km_7d = compute_travel_km(away_team_id)
    
    # Check international break status
    home_post_break = _is_post_international_break(home_team_id, ko_time, international_breaks)
    away_post_break = _is_post_international_break(away_team_id, ko_time, international_breaks)
    
    if home_post_break and away_post_break:
        view.is_post_international_break = 1.0
    elif home_post_break or away_post_break:
        view.is_post_international_break = 0.5
    else:
        view.is_post_international_break = 0.0
    
    return view


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance in km between two (lat, lon) points."""
    R = 6371.0  # Earth radius in km
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c


def _is_post_international_break(team_id: str, fixture_time: datetime, breaks: list[dict]) -> bool:
    """Check if team is returning from an international break."""
    for break_window in breaks:
        try:
            break_end = datetime.fromisoformat(break_window.get('end_utc', '').replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        
        # Within 7 days of international break end?
        if break_end <= fixture_time <= break_end + timedelta(days=7):
            return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Bullet 4: Card-Context View
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CardContextView:
    """Card-context derived view: expected cards from referee + team history.
    
    Fires only when Officials plane is enabled and assignment exists.
    Combines referee rolling stats with team card history.
    """
    fixture_id: str
    
    referee_cards_per_match_smoothed: float = 0.0
    team_cards_per_match_smoothed: float = 0.0
    combined_card_score: float = 0.0


def compute_card_context(
    fixture_id: str,
    referee_id: Optional[str],
    home_team_id: str,
    away_team_id: str,
    referee_profiles: list[dict],
    live_records: list[dict],
    officials_enabled: bool = True,
    cfg_obj=None,
) -> CardContextView:
    """Compute card-context view from referee and team history.
    
    Args:
        fixture_id: The fixture ID
        referee_id: Assigned referee ID (or None)
        home_team_id: Home team ID
        away_team_id: Away team ID
        referee_profiles: List of referee profile records
        live_records: List of live match records for card history
        officials_enabled: Whether Officials plane is enabled
        cfg_obj: Config object
        
    Returns:
        CardContextView with card expectations
    """
    view = CardContextView(fixture_id=fixture_id)
    
    if not officials_enabled or not referee_id:
        # Officials plane disabled or no referee assignment — return zero overlay
        return view
    
    # Find referee profile
    referee_profile = None
    for prof in referee_profiles:
        if prof.get('referee_id') == referee_id:
            referee_profile = prof
            break
    
    if referee_profile:
        view.referee_cards_per_match_smoothed = referee_profile.get('rolling_stats', {}).get('cards_per_match', 0.0)
    
    # Compute team card rates from live records
    def team_cards_per_match(team_id: str) -> float:
        total_cards = 0
        total_matches = 0
        for rec in live_records:
            if rec.get('home_team_id') == team_id:
                total_cards += rec.get('home_cards', 0)
                total_matches += 1
            elif rec.get('away_team_id') == team_id:
                total_cards += rec.get('away_cards', 0)
                total_matches += 1
        
        return total_cards / total_matches if total_matches > 0 else 0.0
    
    home_cards = team_cards_per_match(home_team_id)
    away_cards = team_cards_per_match(away_team_id)
    
    # Combined score: average of referee and team rates
    view.combined_card_score = (view.referee_cards_per_match_smoothed + (home_cards + away_cards) / 2.0) / 2.0
    
    return view


# ═══════════════════════════════════════════════════════════════════════════
# Bullet 5: Narrative-Pressure View
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class NarrativePressureView:
    """Narrative-pressure derived view: editorial sentiment pre-KO.
    
    Fires only when Phase 10 NLP pipeline available and min articles threshold met.
    Uses editorial plane + NLP sentiment outputs.
    """
    fixture_id: str
    
    article_count_72h: int = 0
    sentiment_polarity_72h: float = 0.0
    narrative_score: float = 0.0


def compute_narrative_pressure(
    fixture_id: str,
    fixture_kickoff_utc: str,
    home_team_id: str,
    away_team_id: str,
    editorial_records: list[dict],
    cfg_obj=None,
) -> NarrativePressureView:
    """Compute narrative-pressure view from editorial plane + NLP.
    
    Args:
        fixture_id: The fixture ID
        fixture_kickoff_utc: ISO-8601 fixture kickoff time
        home_team_id: Home team ID
        away_team_id: Away team ID
        editorial_records: List of editorial (article) records
        cfg_obj: Config object
        
    Returns:
        NarrativePressureView with sentiment aggregates
    """
    if cfg_obj is None:
        cfg_obj = cfg
    
    view = NarrativePressureView(fixture_id=fixture_id)
    
    try:
        ko_time = datetime.fromisoformat(fixture_kickoff_utc.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return view
    
    window_start = ko_time - timedelta(hours=72)
    
    # Filter articles for both teams in 72h window
    team_articles = []
    for rec in editorial_records:
        try:
            article_time = datetime.fromisoformat(rec.get('published_at', '').replace('Z', '+00:00'))
        except (ValueError, TypeError):
            continue
        
        if not (window_start <= article_time <= ko_time):
            continue
        
        article_team = rec.get('team_id')
        if article_team not in (home_team_id, away_team_id):
            continue
        
        team_articles.append(rec)
    
    view.article_count_72h = len(team_articles)
    
    # If below minimum threshold, return zero overlay
    if view.article_count_72h < cfg_obj.enrichment_narrative_min_articles:
        return view
    
    # Compute average sentiment
    if team_articles:
        total_sentiment = sum(rec.get('nlp_sentiment', 0.0) for rec in team_articles)
        view.sentiment_polarity_72h = total_sentiment / len(team_articles)
    
    # Narrative score: article count normalized + sentiment weight
    view.narrative_score = (view.article_count_72h / max(1, cfg_obj.enrichment_narrative_min_articles)) * (0.5 + 0.5 * (view.sentiment_polarity_72h + 1.0) / 2.0)
    
    return view


# ═══════════════════════════════════════════════════════════════════════════
# Bullet 6: Event Coalescing Reactor
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CoalescedEvent:
    """Represents a coalesced event ready for publication."""
    fixture_id: str
    timestamp_utc: str
    views: dict  # {view_type: view_data}


class DerivedViewReactor:
    """Idempotent reactor that fires on upstream plane events.
    
    Implements event coalescing per cfg.enrichment_derived_view_coalesce_ms
    to prevent thrashing on high-frequency market updates.
    """
    
    def __init__(self, cfg_obj=None):
        self.cfg = cfg_obj or cfg
        self.coalesce_ms = self.cfg.enrichment_derived_view_coalesce_ms
        self.pending: dict[str, dict] = defaultdict(dict)  # {fixture_id: {view_type: view_obj}}
        self.last_coalesce_time: dict[str, datetime] = {}  # {fixture_id: last_publish_time}
    
    def add_event(
        self,
        fixture_id: str,
        view_type: str,
        view_obj,
        event_time_utc: str,
    ) -> Optional[CoalescedEvent]:
        """Process an incoming event. May return a coalesced event ready to publish.
        
        Args:
            fixture_id: Fixture ID
            view_type: Type of view ('market_movement', 'congestion', 'card_context', 'narrative')
            view_obj: The computed view object
            event_time_utc: ISO-8601 timestamp of the event
            
        Returns:
            CoalescedEvent if the coalesce window has closed, else None
        """
        try:
            event_time = datetime.fromisoformat(event_time_utc.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            event_time = datetime.now(timezone.utc)
        
        self.pending[fixture_id][view_type] = view_obj
        
        last_time = self.last_coalesce_time.get(fixture_id)
        
        if last_time is None:
            # First event for this fixture
            self.last_coalesce_time[fixture_id] = event_time
            return None
        
        elapsed_ms = (event_time - last_time).total_seconds() * 1000
        
        if elapsed_ms >= self.coalesce_ms:
            # Coalesce window has closed — publish
            coalesced = CoalescedEvent(
                fixture_id=fixture_id,
                timestamp_utc=event_time.isoformat(),
                views=dict(self.pending[fixture_id]),
            )
            
            # Reset for next window
            self.pending[fixture_id].clear()
            self.last_coalesce_time[fixture_id] = event_time
            
            return coalesced
        
        return None
    
    def flush(self, fixture_id: str) -> Optional[CoalescedEvent]:
        """Flush any pending events for a fixture (manual trigger)."""
        if fixture_id not in self.pending or not self.pending[fixture_id]:
            return None
        
        now = datetime.now(timezone.utc)
        coalesced = CoalescedEvent(
            fixture_id=fixture_id,
            timestamp_utc=now.isoformat(),
            views=dict(self.pending[fixture_id]),
        )
        
        self.pending[fixture_id].clear()
        self.last_coalesce_time[fixture_id] = now
        
        return coalesced
