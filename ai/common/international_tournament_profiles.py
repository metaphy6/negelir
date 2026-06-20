"""Phase 19.5 — International tournament calibration profiles.

Supports World Cup qualifiers, continental championships, and inter-confederation
play-offs with confederation-specific calibration rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class DensityPenaltyBin:
    """Penalty bin for tournament rotation density."""
    
    min_rotation_days: int
    """Minimum days of rotation (e.g., 3 for a 3-day gap between matches)."""
    
    max_rotation_days: int
    """Maximum days in this bin."""
    
    penalty_multiplier: float
    """Calibration penalty (0.8 = 20% disadvantage, 1.2 = 20% advantage)."""
    
    bin_id: str = ""
    """Unique identifier for this density bin (optional)."""
    
    days_between_matches_min: int = 0
    """Minimum days between matches (optional)."""
    
    days_between_matches_max: int = 100
    """Maximum days between matches (optional)."""
    
    injury_fatigue_penalty_mult: float = 1.0
    """Injury/fatigue penalty multiplier for short-rest scenarios."""


@dataclass(frozen=True)
class TournamentRotationModel:
    """Rotation model for international tournament fixtures."""
    
    model_id: str = ""
    """Unique identifier for this rotation model (optional)."""
    
    confederation: str = ""
    """Confederation this model applies to (e.g., 'UEFA', 'CONMEBOL') (optional)."""
    
    group_stage_rotation_probability: float = 0.0
    """Probability of squad rotation in group stage matches."""
    
    knockout_stage_rotation_probability: float = 0.1
    """Probability of squad rotation in knockout stage matches."""
    
    final_match_rotation_probability: float = 0.0
    """Probability of squad rotation in final match."""
    
    density_bins: list[DensityPenaltyBin] = field(default_factory=list)
    """Penalty bins based on fixture rotation density."""
    
    fixture_frequency_penalty: float = 1.0
    """Penalty for high-frequency fixtures (e.g., 1.05 = 5% disadvantage)."""


@dataclass(frozen=True)
class InternationalTournamentCalibrationProfile:
    """Calibration profile for international tournaments.
    
    Per ROADMAP §19.5, international tournaments have confederation-specific
    calibration rules including rotation penalties and inter-confederation
    neutral home advantage adjustments.
    """
    
    profile_id: str
    """Unique identifier, e.g., 'wc_2026_qualifier_uefa'."""
    
    description: str = ""
    """Human-readable description of this profile."""
    
    tournament_type: Literal["world_cup_qualifier", "continental_championship", "friendly"] = "world_cup_qualifier"
    """Type of tournament."""
    
    confederation: str = ""
    """Confederation, e.g., 'UEFA', 'CONMEBOL', 'CAF' (optional)."""
    
    # Calibration parameters for prediction model
    elo_home_advantage_mult: float = 1.0
    """Multiplier on ELO home advantage (0.0 = neutral, 1.0 = full advantage)."""
    
    dixon_coles_rho_add: float = 0.0
    """Dixon-Coles correlation adjustment for tournament-specific dynamics."""
    
    draw_sample_weight_mult: float = 1.0
    """Weight multiplier on draw samples in training."""
    
    poisson_max_goals_add: float = 0.0
    """Addition to max goals in Poisson model (e.g., 0.5 for high-scoring tournaments)."""
    
    xg_elo_factor_range_mult: float = 1.0
    """Multiplier on expected goals factor range."""
    
    upset_prior: float = 0.05
    """Prior probability of upset (lower-ranked team winning)."""
    
    zero_home_advantage_when_venue_in: tuple[str, ...] = ()
    """Venue types where home advantage is zero (e.g., ('neutral',))."""
    
    rotation_model: TournamentRotationModel | None = None
    """Squad rotation model for this tournament, or None."""
    
    squad_rotation_model: TournamentRotationModel | None = None
    """Squad rotation model (alias for rotation_model for backward compat)."""
    
    fixture_density_penalty_curve: tuple[DensityPenaltyBin, ...] = ()
    """Density penalty curve for fixture rotation."""
    
    home_advantage_host_adjustment: float = 1.0
    """Adjustment for host nation home advantage (>1.0 = advantage)."""
    
    inter_confederation_neutral_home_advantage: bool = False
    """True if inter-confederation play-offs use neutral home advantage (0.0)."""
    
    home_advantage_default: float = 0.8
    """Default home advantage prior for domestic matches."""
    
    underdog_boost: float = 1.0
    """Underdog calibration boost (>1.0 favors lower-ranked teams)."""
    
    two_leg: bool | None = None
    """Whether this tournament uses two-leg ties (knockout rounds)."""
