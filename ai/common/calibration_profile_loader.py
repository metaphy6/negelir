"""
Phase 13.2 — Calibration profile loader and validator.

Loads all YAML files from ai/common/calibration_profiles/, validates against
the JSONSchema, and enforces:
  - Schema validation (profile_id, description, numeric bounds)
  - Unique profile_id values (filename must match profile_id)
  - No unknown profiles referenced
  - Result is immutable (frozen objects)

Per COMPETITIONS.md §4.2 and Phase 13.2 definition-of-done.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from common.logger import get_logger

logger = get_logger(__name__)

# Expected calibration profile IDs per COMPETITIONS.md §4.2
EXPECTED_PROFILE_IDS = frozenset({
    "league_round_robin",
    "domestic_cup_early_round",
    "domestic_cup_late_round",
    "super_cup_one_off",
    "knockout_continental_club",
    "group_continental_club",
    "qualifier_continental_club",
    "international_group_stage",
    "international_knockout",
    "international_qualifier_competitive",
    "international_friendly_excluded",
})


@dataclass(frozen=True)
class TwoLegRules:
    """Rules for two-leg tie aggregation."""
    away_goals_rule_active_until: Optional[str]  # ISO-8601 date or None
    aggregate_logic: str
    penalty_shootout_modeled: bool


@dataclass(frozen=True)
class CalibrationProfile:
    """Immutable representation of a calibration profile."""
    profile_id: str
    description: str
    elo_home_advantage_mult: float
    dixon_coles_rho_add: float
    draw_sample_weight_mult: float
    poisson_max_goals_add: float
    xg_elo_factor_range_mult: float
    upset_prior: float
    zero_home_advantage_when_venue_in: tuple[str, ...]
    two_leg: Optional[TwoLegRules] = None

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


def _load_schema() -> dict[str, Any]:
    """Load the JSONSchema from disk."""
    schema_path = Path(__file__).resolve().parent / "schemas" / "calibration_profile.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    
    with open(schema_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate_against_schema(data: dict[str, Any], schema: dict[str, Any], profile_id: str) -> None:
    """Validate a single profile against the JSONSchema."""
    if jsonschema is None:
        raise ImportError("jsonschema not installed. Install with: pip install jsonschema")
    
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Calibration profile '{profile_id}' validation failed: {exc.message}"
        ) from exc


def _load_profile_yaml(profile_path: Path) -> dict[str, Any]:
    """Load a single YAML calibration profile."""
    if yaml is None:
        raise ImportError("PyYAML not installed. Install with: pip install pyyaml")
    
    with open(profile_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    
    if not isinstance(data, dict):
        raise TypeError(
            f"Profile {profile_path.name}: root must be a dict, got {type(data).__name__}"
        )
    
    return data


def _load_all_profiles() -> Dict[str, CalibrationProfile]:
    """Load and validate all calibration profiles from the profiles directory."""
    profiles_dir = Path(__file__).resolve().parent / "calibration_profiles"
    
    if not profiles_dir.exists():
        raise FileNotFoundError(f"Calibration profiles directory not found: {profiles_dir}")
    
    schema = _load_schema()
    profiles: Dict[str, CalibrationProfile] = {}
    
    # Find all .yaml files in the profiles directory
    yaml_files = sorted(profiles_dir.glob("*.yaml"))
    
    if not yaml_files:
        raise ValueError(f"No calibration profile YAML files found in {profiles_dir}")
    
    for profile_path in yaml_files:
        # Load and validate against schema
        raw_data = _load_profile_yaml(profile_path)
        profile_id = raw_data.get("profile_id")
        
        if not profile_id:
            raise ValueError(f"{profile_path.name}: missing profile_id field")
        
        # Validate filename matches profile_id
        expected_filename = f"{profile_id}.yaml"
        if profile_path.name != expected_filename:
            raise ValueError(
                f"Profile filename mismatch: {profile_path.name} does not match "
                f"profile_id '{profile_id}' (expected {expected_filename})"
            )
        
        # Validate against schema
        _validate_against_schema(raw_data, schema, profile_id)
        
        # Parse two_leg rules if present
        two_leg_data = raw_data.get("two_leg")
        two_leg_rules = None
        if two_leg_data:
            two_leg_rules = TwoLegRules(
                away_goals_rule_active_until=two_leg_data.get("away_goals_rule_active_until"),
                aggregate_logic=two_leg_data.get("aggregate_logic", "sum_goals"),
                penalty_shootout_modeled=two_leg_data.get("penalty_shootout_modeled", True),
            )
        
        # Create immutable profile object (validates ranges in __post_init__)
        profile = CalibrationProfile(
            profile_id=profile_id,
            description=raw_data.get("description", ""),
            elo_home_advantage_mult=raw_data.get("elo_home_advantage_mult", 1.0),
            dixon_coles_rho_add=raw_data.get("dixon_coles_rho_add", 0.0),
            draw_sample_weight_mult=raw_data.get("draw_sample_weight_mult", 1.0),
            poisson_max_goals_add=raw_data.get("poisson_max_goals_add", 0.0),
            xg_elo_factor_range_mult=raw_data.get("xg_elo_factor_range_mult", 1.0),
            upset_prior=raw_data.get("upset_prior", 0.0),
            zero_home_advantage_when_venue_in=tuple(
                raw_data.get("zero_home_advantage_when_venue_in", [])
            ),
            two_leg=two_leg_rules,
        )
        
        profiles[profile_id] = profile
    
    return profiles


def load_calibration_profiles() -> Mapping[str, CalibrationProfile]:
    """
    Load and validate all calibration profiles from ai/common/calibration_profiles/.
    
    Validates:
      1. All YAML files are well-formed
      2. Each matches JSONSchema (types, required fields, numeric bounds)
      3. Filename matches profile_id field
      4. All numeric fields are within valid ranges
      5. All expected profile IDs (per COMPETITIONS.md §4.2) are present
      6. All fields converted to immutable types
    
    Performance:
      - Loads N profiles in O(N) time
      - Subsequent O(1) lookups by profile_id
    
    Returns:
        Mapping[str, CalibrationProfile]: Immutable dict mapping profile_id → CalibrationProfile
    
    Raises:
        FileNotFoundError: If profiles directory or schema not found
        ValueError: If validation fails (filename mismatch, numeric range, missing profiles, etc.)
        ImportError: If required packages (yaml, jsonschema) not installed
    """
    profiles = _load_all_profiles()
    
    # Check that all expected profiles are present
    missing_profiles = EXPECTED_PROFILE_IDS - set(profiles.keys())
    if missing_profiles:
        raise ValueError(
            f"Missing calibration profiles (per COMPETITIONS.md §4.2): {sorted(missing_profiles)}"
        )
    
    # Build immutable mapping
    return MappingProxyType(profiles)


# Module-level singleton loaded at import time
try:
    import time as _time_module
    _load_start = _time_module.perf_counter()
    CALIBRATION_PROFILES: Mapping[str, CalibrationProfile] = load_calibration_profiles()
    _load_elapsed_ms = (_time_module.perf_counter() - _load_start) * 1000
    logger.debug(
        f"Loaded {len(CALIBRATION_PROFILES)} calibration profiles in {_load_elapsed_ms:.1f}ms"
    )
except Exception as exc:
    logger.error(f"Failed to load calibration profiles: {exc}")
    CALIBRATION_PROFILES = MappingProxyType({})  # type: ignore
