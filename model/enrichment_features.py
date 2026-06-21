"""Phase 21.1 §21.1 — Roster-state enrichment features.

Feature computation for squad composition, player transitions, and leadership impact:
  - squad_strength_delta: Average rating change from official transfers
  - cohesion_penalty: Decaying penalty for new arrivals over first 4 appearances
  - departure_shock: Penalty when top-quartile player left within 14 days

All coefficients come from config (§21.0); no hardcoded values.

Binding per ROADMAP §21.1 bullet 5 and ENRICHMENT_DATA.md §2.3.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from common.config import Config


def compute_squad_strength_delta(
    team_id: str,
    player_id: str,
    old_rating: Optional[float],
    new_rating: Optional[float],
    current_squad_size: int,
) -> float:
    """Compute squad strength change from a player transfer.
    
    Represents the impact of a single transfer on team strength.
    Called when a new official transfer arrives.
    
    Args:
        team_id: Team ID (for logging/audit)
        player_id: Player ID involved in transfer
        old_rating: Player's rating (or None if new signing)
        new_rating: Player's updated rating
        current_squad_size: Current squad size (for normalization)
        
    Returns:
        Squad strength delta (can be positive/negative/zero)
    """
    if old_rating is None or new_rating is None:
        # Missing rating data — no delta
        return 0.0
    
    if current_squad_size == 0:
        # Defensive: prevent division by zero
        return 0.0
    
    # Delta = (new - old) / squad_size (normalized to squad size)
    delta = (new_rating - old_rating) / current_squad_size
    
    return delta


def compute_cohesion_penalty(
    appearances_since_arrival: int,
    cfg: Config,
) -> float:
    """Compute cohesion penalty for a new player arrival.
    
    New arrivals incur a decaying penalty over their first 4 league appearances.
    The penalty curve is configured in cfg.enrichment_cohesion_penalty_curve.
    
    Args:
        appearances_since_arrival: Number of appearances since joining (0–4+)
        cfg: Config object with enrichment_cohesion_penalty_curve
        
    Returns:
        Cohesion penalty (negative value to subtract from xG)
    """
    # Curve is indexed by appearance count: [appear_0, appear_1, appear_2, appear_3]
    # appearances_since_arrival = 0 means not yet appeared (use index 0)
    # appearances_since_arrival = 4+ means penalty expired (return 0)
    
    curve = cfg.enrichment_cohesion_penalty_curve
    
    if appearances_since_arrival >= len(curve):
        # Penalty has expired after configured appearances
        return 0.0
    
    # Return the penalty for this appearance count (negative)
    penalty_value = curve[appearances_since_arrival]
    return -penalty_value  # Negative penalty to apply to xG


def compute_departure_shock(
    departure_date_utc: str,
    player_rating: Optional[float],
    squad_ratings: list[float],
    cfg: Config,
    current_date_utc: Optional[str] = None,
) -> float:
    """Compute departure shock when a top-quartile player left recently.
    
    Triggered when a player rated in the top quartile of the squad left
    within the past 14 days.
    
    Args:
        departure_date_utc: ISO-8601 UTC date when player left
        player_rating: Player's rating (or None if not ranked)
        squad_ratings: List of ratings for the current squad
        cfg: Config object with enrichment_departure_shock coefficient
        current_date_utc: Current date ISO-8601 UTC (default: now)
        
    Returns:
        Departure shock penalty (negative value, or 0 if not triggered)
    """
    if current_date_utc is None:
        current_date_utc = datetime.now(timezone.utc).isoformat()
    
    if player_rating is None or not squad_ratings:
        # Missing data — no shock
        return 0.0
    
    # Parse dates
    try:
        depart_dt = datetime.fromisoformat(departure_date_utc.replace('Z', '+00:00'))
        current_dt = datetime.fromisoformat(current_date_utc.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return 0.0
    
    # Check if within 14 days
    days_since_departure = (current_dt - depart_dt).days
    if days_since_departure < 0 or days_since_departure >= 14:
        # Departure was too long ago or in the future
        return 0.0
    
    # Check if player was top-quartile
    # Top quartile = >= 75th percentile
    sorted_ratings = sorted(squad_ratings, reverse=True)
    if not sorted_ratings:
        return 0.0
    
    quartile_threshold = sorted_ratings[max(0, len(sorted_ratings) // 4)]
    
    if player_rating >= quartile_threshold:
        # Player was in top quartile — apply shock
        shock_coefficient = cfg.enrichment_departure_shock
        return -shock_coefficient  # Negative to penalize xG
    
    return 0.0


__all__ = [
    "compute_squad_strength_delta",
    "compute_cohesion_penalty",
    "compute_departure_shock",
]
