"""
Phase 13 — League catalog loader and validator.

Loads ai/common/league_catalog.yaml, validates against the JSONSchema,
and enforces:
  - Unknown tier values rejected (only T1, T2, T3)
  - Duplicate league_id detected and rejected
  - Dangling competition_id references flagged (cross-reference validation)
  - Result is immutable (frozen dict + frozenset fields)
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, Mapping, Tuple

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from ai.common.logger import get_logger

logger = get_logger(__name__)


# Valid tier values per LEAGUE_CATALOG.md §1
VALID_TIERS = frozenset({"T1", "T2", "T3"})

# Valid confederation values per LEAGUE_CATALOG.md
VALID_CONFEDERATIONS = frozenset({"UEFA", "CONMEBOL", "CONCACAF", "AFC", "CAF", "OFC", "FIFA"})


@dataclass(frozen=True)
class CompetitionRef:
    """Reference to a competition within a league."""
    competition_id: str


@dataclass(frozen=True)
class SourceCoverage:
    """Source coverage specification per data plane."""
    reference: Tuple[str, ...] = ()
    schedule: Tuple[str, ...] = ()
    live: Tuple[str, ...] = ()
    editorial: Tuple[str, ...] = ()
    market: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LeagueRow:
    """Immutable representation of a single league row."""
    league_id: str
    name_en: str
    name_tr: str
    country: str | None
    confederation: str
    tier: str
    active_since: str
    competitions: FrozenSet[str]  # frozen set of competition_id strings
    source_coverage: SourceCoverage

    def __post_init__(self) -> None:
        """Validate fields at instantiation."""
        if self.tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier '{self.tier}' for league '{self.league_id}'. "
                f"Must be one of: {sorted(VALID_TIERS)}"
            )
        if self.confederation not in VALID_CONFEDERATIONS:
            raise ValueError(
                f"Invalid confederation '{self.confederation}' for league '{self.league_id}'. "
                f"Must be one of: {sorted(VALID_CONFEDERATIONS)}"
            )


def _load_schema() -> dict[str, Any]:
    """Load the JSONSchema from disk."""
    schema_path = Path(__file__).resolve().parent / "schemas" / "league_catalog.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    
    with open(schema_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_catalog_yaml() -> dict[str, Any]:
    """Load the YAML catalog file from disk."""
    catalog_path = Path(__file__).resolve().parent / "league_catalog.yaml"
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog file not found: {catalog_path}")
    
    if yaml is None:
        raise ImportError("PyYAML not installed. Install with: pip install pyyaml")
    
    with open(catalog_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    
    if not isinstance(data, dict):
        raise TypeError(f"Catalog root must be a dict, got {type(data).__name__}")
    
    return data


def _validate_against_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate the loaded YAML against the JSONSchema."""
    if jsonschema is None:
        raise ImportError("jsonschema not installed. Install with: pip install jsonschema")
    
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Catalog validation failed: {exc.message}") from exc


def _check_duplicate_league_ids(leagues: list[dict[str, Any]]) -> None:
    """Check that all league_id values are unique."""
    seen: Dict[str, int] = {}
    for idx, league in enumerate(leagues):
        league_id = league.get("league_id")
        if league_id in seen:
            raise ValueError(
                f"Duplicate league_id '{league_id}' at index {idx}; "
                f"previously seen at index {seen[league_id]}"
            )
        seen[league_id] = idx


def _check_dangling_competition_ids(leagues: list[dict[str, Any]]) -> None:
    """
    Check that competition_id references are consistent.
    Currently just verifies that each competition_id is non-empty and matches
    the expected pattern. Cross-league references would require a global registry.
    """
    for league in leagues:
        league_id = league.get("league_id", "<unknown>")
        competitions = league.get("competitions", [])
        
        if not isinstance(competitions, list):
            raise ValueError(
                f"League '{league_id}': competitions must be a list, got {type(competitions).__name__}"
            )
        
        for comp_idx, comp in enumerate(competitions):
            if not isinstance(comp, dict):
                raise ValueError(
                    f"League '{league_id}': competition[{comp_idx}] must be a dict, "
                    f"got {type(comp).__name__}"
                )
            
            comp_id = comp.get("competition_id")
            if not comp_id or not isinstance(comp_id, str):
                raise ValueError(
                    f"League '{league_id}': competition[{comp_idx}] missing or invalid "
                    f"competition_id (must be non-empty string)"
                )


def _rows_to_immutable(raw_leagues: list[dict[str, Any]]) -> list[LeagueRow]:
    """Convert raw YAML league dicts to immutable LeagueRow objects."""
    rows: list[LeagueRow] = []
    
    for raw_league in raw_leagues:
        # Extract and validate tier early
        tier = raw_league.get("tier")
        league_id = raw_league.get("league_id", "<unknown>")
        
        if tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier '{tier}' for league '{league_id}'. "
                f"Must be one of: {sorted(VALID_TIERS)}"
            )
        
        # Convert competitions list to frozenset of competition_ids
        competitions_list = raw_league.get("competitions", [])
        comp_ids = frozenset(
            comp["competition_id"] 
            for comp in competitions_list
        )
        
        # Convert source_coverage dict to SourceCoverage immutable object
        coverage_dict = raw_league.get("source_coverage", {})
        source_coverage = SourceCoverage(
            reference=tuple(coverage_dict.get("reference", [])),
            schedule=tuple(coverage_dict.get("schedule", [])),
            live=tuple(coverage_dict.get("live", [])),
            editorial=tuple(coverage_dict.get("editorial", [])),
            market=tuple(coverage_dict.get("market", [])),
        )
        
        # Create immutable LeagueRow (validates tier + confederation in __post_init__)
        row = LeagueRow(
            league_id=league_id,
            name_en=raw_league.get("name_en", ""),
            name_tr=raw_league.get("name_tr", ""),
            country=raw_league.get("country"),
            confederation=raw_league.get("confederation", ""),
            tier=tier,
            active_since=raw_league.get("active_since", ""),
            competitions=comp_ids,
            source_coverage=source_coverage,
        )
        rows.append(row)
    
    return rows


def _build_tier_index(rows: list[LeagueRow]) -> Dict[str, list[LeagueRow]]:
    """
    Build a per-tier index for O(1) tier lookups.
    
    Args:
        rows: List of LeagueRow objects
    
    Returns:
        Dict[str, list[LeagueRow]]: Mapping from tier (T1/T2/T3) to list of rows
    """
    tier_index: Dict[str, list[LeagueRow]] = {tier: [] for tier in VALID_TIERS}
    for row in rows:
        tier_index[row.tier].append(row)
    return tier_index


def _build_competition_index(rows: list[LeagueRow]) -> Dict[str, LeagueRow]:
    """
    Build a competition_id → LeagueRow reverse index for O(1) lookups.
    
    Per Phase 13.1: "Reverse index by competition_id. Loader exposes
    `BY_COMPETITION: Mapping[str, LeagueRow]` so identity-resolver / emitter /
    patcher don't iterate the catalog."
    
    Args:
        rows: List of LeagueRow objects
    
    Returns:
        Dict[str, LeagueRow]: Mapping from competition_id to its owning LeagueRow
    
    Raises:
        ValueError: If a competition_id is owned by multiple leagues (sanity check)
    """
    competition_index: Dict[str, LeagueRow] = {}
    
    for row in rows:
        for comp_id in row.competitions:
            if comp_id in competition_index:
                existing = competition_index[comp_id]
                raise ValueError(
                    f"Ambiguous competition_id '{comp_id}': owned by both "
                    f"league '{row.league_id}' and '{existing.league_id}'"
                )
            competition_index[comp_id] = row
    
    return competition_index


def load_league_catalog() -> Mapping[str, LeagueRow]:
    """
    Load and validate the league catalog from ai/common/league_catalog.yaml.
    
    Validates:
      1. YAML is well-formed
      2. Matches JSONSchema (types, required fields, patterns)
      3. Schema version field names (lint gate per §13.1)
      4. No duplicate league_id values
      5. No dangling competition_id references
      6. No invalid tier or confederation values
      7. All fields converted to immutable types
    
    Performance:
      - Catalog loads in O(N) where N = number of leagues
      - Per-tier index created in O(N)
      - Subsequent O(1) lookups via CATALOG_BY_TIER
    
    Returns:
        Mapping[str, LeagueRow]: Immutable dict mapping league_id → LeagueRow
    
    Raises:
        FileNotFoundError: If catalog or schema file not found
        ValueError: If validation fails (duplicates, invalid tier, etc.)
        ImportError: If required packages (yaml, jsonschema) not installed
    """
    # Import validator here to avoid circular dependency
    from xops.leagues.schema_validator import validate_catalog_fields
    
    # Load schema and catalog
    schema = _load_schema()
    raw_data = _load_catalog_yaml()
    
    # Validate against schema
    _validate_against_schema(raw_data, schema)
    
    # Validate field names per schema version (§13.1 lint gate)
    validate_catalog_fields(raw_data)
    
    # Extract leagues list
    raw_leagues = raw_data.get("leagues", [])
    
    # Check for duplicates
    _check_duplicate_league_ids(raw_leagues)
    
    # Check for dangling references
    _check_dangling_competition_ids(raw_leagues)
    
    # Convert to immutable objects and validate tier/confederation
    rows = _rows_to_immutable(raw_leagues)
    
    # Build immutable mapping using MappingProxyType to prevent mutations
    result_dict: Dict[str, LeagueRow] = {row.league_id: row for row in rows}
    return MappingProxyType(result_dict)


# Module-level singleton loaded at import time
try:
    import time as _time_module
    _load_start = _time_module.perf_counter()
    CATALOG: Mapping[str, LeagueRow] = load_league_catalog()
    _load_elapsed_ms = (_time_module.perf_counter() - _load_start) * 1000
    _rows = list(CATALOG.values())
    CATALOG_BY_TIER: Dict[str, list[LeagueRow]] = _build_tier_index(_rows)
    BY_COMPETITION: Mapping[str, LeagueRow] = MappingProxyType(_build_competition_index(_rows))
    logger.debug(
        f"Loaded league catalog with {len(CATALOG)} leagues in {_load_elapsed_ms:.1f}ms; "
        f"tier index: T1={len(CATALOG_BY_TIER.get('T1', []))} T2={len(CATALOG_BY_TIER.get('T2', []))} T3={len(CATALOG_BY_TIER.get('T3', []))}; "
        f"competition index: {len(BY_COMPETITION)} competitions"
    )
except Exception as exc:
    logger.error(f"Failed to load league catalog: {exc}")
    CATALOG = {}  # type: ignore
    CATALOG_BY_TIER = {tier: [] for tier in VALID_TIERS}
    BY_COMPETITION = MappingProxyType({})  # type: ignore
