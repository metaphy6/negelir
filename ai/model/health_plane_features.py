"""Phase 21.2 — Health plane feature computation.

Implements:
- Bullet 7: Squad availability vector for team_strength reduction
- Bullet 8: International window calendar filtering

Per ENRICHMENT_DATA.md §3.3 and ROADMAP §21.2 bullets 7-8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from ai.common.config import cfg
from ai.common.logger import get_logger

log = get_logger("model.health_plane_features")


@dataclass
class InternationalWindowFilter:
    """Loads confederation calendar and filters international_duty status."""

    confederation_calendar: Dict[str, List[Dict[str, str]]]
    """confederation_id → list of {start_date, end_date, description}."""

    @classmethod
    def load_from_file(cls, filepath: str) -> InternationalWindowFilter:
        """Load from confederation_calendars.json.
        
        Per ROADMAP §21.2 §8 and config key ENRICHMENT_CONFEDERATION_CALENDAR_PATH.
        """
        with open(filepath, "r") as f:
            data = json.load(f)

        calendar = {}
        for conf in data.get("confederations", []):
            conf_id = conf.get("confederation_id")
            breaks = conf.get("international_breaks", [])
            calendar[conf_id] = breaks

        return cls(confederation_calendar=calendar)

    def is_international_window(
        self, date_str: str, confederation_id: str
    ) -> bool:
        """Check if a date falls within an international break for a confederation.
        
        Args:
            date_str: ISO date string (YYYY-MM-DD)
            confederation_id: e.g., 'uefa', 'conmebol', 'afc'

        Returns:
            True if date is within an international break window.
        """
        breaks = self.confederation_calendar.get(confederation_id, [])
        
        try:
            date = datetime.fromisoformat(date_str).date()
        except (ValueError, AttributeError):
            return False

        for break_window in breaks:
            start = datetime.fromisoformat(break_window["start_date"]).date()
            end = datetime.fromisoformat(break_window["end_date"]).date()
            if start <= date <= end:
                return True

        return False


@dataclass
class SquadAvailabilityVector:
    """Computes squad availability reduction to team_strength feature.
    
    Per ENRICHMENT_DATA.md §3.3:
    - team_strength reduced by Σ(unavailable_player_rating × starter_likelihood)
    - for non-fit statuses only (international_duty excluded)
    - Proofreader widens CI when >30% of XI has doubtful status
    """

    ci_widen_threshold: float = 0.30
    """Fraction of starting XI with doubtful status to trigger CI widening.
    
    From cfg.enrichment_health_ci_widen_threshold (default 0.30).
    """

    def compute_team_strength_reduction(
        self,
        squad_players: List[Dict[str, any]],  # {player_id, rating, starter_likelihood, availability_status}
        available_player_ids: set,  # players with status='fit'
        international_duty_player_ids: set,  # players with status='international_duty' (excluded from penalty)
    ) -> float:
        """Compute the reduction amount to apply to team_strength.
        
        Args:
            squad_players: List of squad member dicts with rating and starter_likelihood
            available_player_ids: Set of player_ids with status='fit'
            international_duty_player_ids: Set of player_ids with status='international_duty'
                (these do NOT count as unavailable for squad-strength penalty)

        Returns:
            Reduction amount (negative value to subtract from team_strength).
        """
        reduction = 0.0

        for player in squad_players:
            player_id = player.get("player_id")
            
            # Skip if player is fit or on international duty
            if player_id in available_player_ids or player_id in international_duty_player_ids:
                continue

            # Player is unavailable (doubtful, out, suspended, rest)
            rating = player.get("rating", 0.5)  # Normalized 0-1
            starter_likelihood = player.get("starter_likelihood", 0.0)  # Normalized 0-1

            reduction += rating * starter_likelihood

        return -reduction  # Negative = penalty

    def compute_uncertainty_ratio(
        self,
        squad_players: List[Dict[str, any]],
        doubtful_player_ids: set,
    ) -> float:
        """Compute fraction of starting XI with doubtful status.
        
        Used by proofreader to decide CI widening (bullet 7).
        
        Returns:
            Fraction 0.0-1.0 of starting XI with doubtful status.
        """
        starting_xi_count = sum(
            1 for p in squad_players if p.get("starter_likelihood", 0.0) > 0.0
        )
        if starting_xi_count == 0:
            return 0.0

        doubtful_in_xi = sum(
            1 for p in squad_players
            if p.get("player_id") in doubtful_player_ids
            and p.get("starter_likelihood", 0.0) > 0.0
        )

        return doubtful_in_xi / starting_xi_count

    def should_widen_ci(self, uncertainty_ratio: float) -> bool:
        """Determine if proofreader should widen CIs.
        
        Per ROADMAP §21.2 bullet 7:
        Widen when >30% of the modelled starting XI has doubtful status.
        """
        return uncertainty_ratio > self.ci_widen_threshold
