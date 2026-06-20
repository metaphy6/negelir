"""Phase 19.5 — International tournament calibration profile subclass.

Extends CalibrationProfile with tournament-specific fields for WC qualifiers
and continental championships: squad rotation models, fixture density penalties,
and host nation advantages.

Note: This module is defined in the Phase 22+ layout (root/common).
It defines InternationalTournamentCalibrationProfile as a protocol/interface
for tournament-specific calibration data. The actual CalibrationProfile
base class is in ai/common/calibration_profile_loader.py during the
transitional phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict


@dataclass(frozen=True)
class DensityPenaltyBin:
    """A fixture-density penalty bin for tournament fixture congestion.
    
    As a tournament progresses through group stage with tight fixture scheduling,
    injury and fatigue effects increase. This represents one bin in a curve
    mapping (days_between_matches) → (injury_fatigue_penalty_mult).
    """

    days_between_matches_min: float
    """Minimum days between matches (inclusive) for this bin."""

    days_between_matches_max: float
    """Maximum days between matches (inclusive) for this bin."""

    injury_fatigue_penalty_mult: float
    """Multiplicative adjustment to injury/fatigue risk. 1.0 = baseline, >1.0 = increased risk."""


@dataclass(frozen=True)
class TournamentRotationModel:
    """Squad rotation probability model for international tournaments.
    
    Different than domestic leagues: international squads rotate players
    more heavily during group stages (resting for knockouts) and less
    during key knockout matches.
    """

    group_stage_rotation_probability: float
    """Probability a player is rotated (rest day, substitution, etc.) in a group-stage match.
    Typically 0.25–0.45 (vs ~0.10–0.20 in domestic leagues)."""

    knockout_stage_rotation_probability: float
    """Probability a player is rotated in a knockout match. Typically 0.05–0.15."""

    final_match_rotation_probability: float
    """Probability a player is rotated in the final. Typically 0.02–0.08."""


@dataclass(frozen=True)
class InternationalTournamentCalibrationProfile:
    """International tournament calibration profile with tournament-specific fields.
    
    Used for wc_qualifier and continental_championship formats.
    In Phase 22+ this would subclass CalibrationProfile; during the transition
    it acts as a standalone data carrier that includes tournament-specific overlays.
    """

    profile_id: str
    """Unique profile identifier."""

    description: str
    """Human-readable description of the profile."""

    # Base calibration parameters
    elo_home_advantage_mult: float
    """Multiplicative overlay on home advantage (e.g., 0.5 for neutral venues)."""

    dixon_coles_rho_add: float
    """Additive adjustment to Dixon-Coles rho."""

    draw_sample_weight_mult: float
    """Multiplicative overlay on draw sample weight."""

    poisson_max_goals_add: float
    """Additive adjustment to max goals in tail distribution."""

    xg_elo_factor_range_mult: float
    """Multiplicative variance scale for xG-Elo interaction."""

    upset_prior: float
    """Additive prior on the underdog column."""

    zero_home_advantage_when_venue_in: tuple[str, ...]
    """Venue policies that force home advantage to zero."""

    # Tournament-specific fields
    squad_rotation_model: TournamentRotationModel
    """Squad rotation probabilities for group/knockout/final stages."""

    fixture_density_penalty_curve: tuple[DensityPenaltyBin, ...]
    """Ordered list of fixture-density penalty bins."""

    home_advantage_host_adjustment: float
    """Home-advantage multiplier for host nation (when host_nation_flag=True)."""

    # Optional fields (must come after required fields)
    two_leg: Optional[dict[str, Any]] = None
    """Optional section: tie-aggregation rules for two-leg format."""

    def __post_init__(self) -> None:
        """Validate fields at instantiation."""
        if not self.profile_id or not isinstance(self.profile_id, str):
            raise ValueError(f"Invalid profile_id: must be non-empty string, got {self.profile_id}")

        # Validate numeric ranges
        if not (0 <= self.elo_home_advantage_mult <= 2.0):
            raise ValueError(
                f"Profile '{self.profile_id}': elo_home_advantage_mult must be in [0, 2.0], "
                f"got {self.elo_home_advantage_mult}"
            )
        if not (-0.5 <= self.dixon_coles_rho_add <= 0.5):
            raise ValueError(
                f"Profile '{self.profile_id}': dixon_coles_rho_add must be in [-0.5, 0.5], "
                f"got {self.dixon_coles_rho_add}"
            )
        if not (0.1 <= self.draw_sample_weight_mult <= 2.0):
            raise ValueError(
                f"Profile '{self.profile_id}': draw_sample_weight_mult must be in [0.1, 2.0], "
                f"got {self.draw_sample_weight_mult}"
            )
        if not (-2 <= self.poisson_max_goals_add <= 3):
            raise ValueError(
                f"Profile '{self.profile_id}': poisson_max_goals_add must be in [-2, 3], "
                f"got {self.poisson_max_goals_add}"
            )
        if not (0.5 <= self.xg_elo_factor_range_mult <= 2.0):
            raise ValueError(
                f"Profile '{self.profile_id}': xg_elo_factor_range_mult must be in [0.5, 2.0], "
                f"got {self.xg_elo_factor_range_mult}"
            )
        if not (0 <= self.upset_prior <= 0.2):
            raise ValueError(
                f"Profile '{self.profile_id}': upset_prior must be in [0, 0.2], "
                f"got {self.upset_prior}"
            )

        # Validate squad rotation probabilities
        for prob_val, prob_name in [
            (self.squad_rotation_model.group_stage_rotation_probability, "group_stage"),
            (self.squad_rotation_model.knockout_stage_rotation_probability, "knockout_stage"),
            (self.squad_rotation_model.final_match_rotation_probability, "final_match"),
        ]:
            if not (0.0 <= prob_val <= 1.0):
                raise ValueError(
                    f"Profile '{self.profile_id}': squad_rotation_model.{prob_name}_rotation_probability "
                    f"must be in [0.0, 1.0], got {prob_val}"
                )

        # Validate home_advantage_host_adjustment
        if not (0.5 <= self.home_advantage_host_adjustment <= 2.0):
            raise ValueError(
                f"Profile '{self.profile_id}': home_advantage_host_adjustment must be in [0.5, 2.0], "
                f"got {self.home_advantage_host_adjustment}"
            )

        # Validate fixture density penalty curve
        if not self.fixture_density_penalty_curve:
            raise ValueError(
                f"Profile '{self.profile_id}': fixture_density_penalty_curve must not be empty"
            )

        for i, bin_ in enumerate(self.fixture_density_penalty_curve):
            if bin_.days_between_matches_min > bin_.days_between_matches_max:
                raise ValueError(
                    f"Profile '{self.profile_id}': fixture_density_penalty_curve[{i}] has "
                    f"days_between_matches_min ({bin_.days_between_matches_min}) > "
                    f"days_between_matches_max ({bin_.days_between_matches_max})"
                )
            if not (0.5 <= bin_.injury_fatigue_penalty_mult <= 2.0):
                raise ValueError(
                    f"Profile '{self.profile_id}': fixture_density_penalty_curve[{i}].injury_fatigue_penalty_mult "
                    f"must be in [0.5, 2.0], got {bin_.injury_fatigue_penalty_mult}"
                )

        # Check bins are non-overlapping
        for i in range(len(self.fixture_density_penalty_curve) - 1):
            current_max = self.fixture_density_penalty_curve[i].days_between_matches_max
            next_min = self.fixture_density_penalty_curve[i + 1].days_between_matches_min
            if current_max >= next_min:
                raise ValueError(
                    f"Profile '{self.profile_id}': fixture_density_penalty_curve bins overlap "
                    f"at index {i}/{i+1}: [{current_max}] >= [{next_min}]"
                )
