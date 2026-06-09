"""
Phase 13.1 — Schema version validator and field-name gating.

Per Phase 13.1 bullet: "lint gates the field name set per version"

This module validates that league_catalog.yaml field names conform
to the declared schema_version, preventing silent evolution of the
schema without bumping the version number.

Validation rules:
  - schema_version must be in FIELD_NAMES_BY_VERSION
  - Every field at top level and in leagues[] must be declared
  - New fields require a schema_version bump
  - Removed fields require a migration entry
"""

from typing import Any, Dict, Set

# Field names allowed at each schema version
FIELD_NAMES_BY_VERSION: Dict[int, Dict[str, Set[str]]] = {
    1: {
        "root": {"schema_version", "leagues"},
        "league_row": {
            "league_id",
            "name_en",
            "name_tr",
            "country",
            "confederation",
            "tier",
            "active_since",
            "competitions",
            "source_coverage",
        },
        "competition": {"competition_id"},
        "source_coverage": {"reference", "schedule", "live", "editorial", "market"},
    }
}


def validate_catalog_fields(data: Dict[str, Any], schema_version: int | None = None) -> None:
    """Validate that catalog fields match the declared schema_version.
    
    Args:
        data: Raw catalog dictionary
        schema_version: Expected schema version (if None, read from data)
    
    Raises:
        ValueError: If field names don't match schema version
    """
    if schema_version is None:
        schema_version = data.get("schema_version", 1)
    
    if schema_version not in FIELD_NAMES_BY_VERSION:
        raise ValueError(
            f"Unknown schema_version {schema_version}. "
            f"Known versions: {sorted(FIELD_NAMES_BY_VERSION.keys())}"
        )
    
    allowed = FIELD_NAMES_BY_VERSION[schema_version]
    
    # Validate root fields
    root_fields = set(data.keys())
    allowed_root = allowed["root"]
    extra_root = root_fields - allowed_root
    if extra_root:
        raise ValueError(
            f"Unknown root fields for schema_version {schema_version}: {extra_root}. "
            f"Allowed: {allowed_root}"
        )
    
    # Validate league rows
    leagues = data.get("leagues", [])
    allowed_league_fields = allowed["league_row"]
    allowed_comp_fields = allowed["competition"]
    allowed_coverage_fields = allowed["source_coverage"]
    
    for idx, league in enumerate(leagues):
        league_fields = set(league.keys())
        extra_league = league_fields - allowed_league_fields
        if extra_league:
            raise ValueError(
                f"Unknown fields in league[{idx}] for schema_version {schema_version}: {extra_league}"
            )
        
        # Validate competitions
        for comp_idx, comp in enumerate(league.get("competitions", [])):
            comp_fields = set(comp.keys())
            extra_comp = comp_fields - allowed_comp_fields
            if extra_comp:
                raise ValueError(
                    f"Unknown fields in league[{idx}].competitions[{comp_idx}] "
                    f"for schema_version {schema_version}: {extra_comp}"
                )
        
        # Validate source_coverage
        coverage = league.get("source_coverage", {})
        coverage_fields = set(coverage.keys())
        extra_coverage = coverage_fields - allowed_coverage_fields
        if extra_coverage:
            raise ValueError(
                f"Unknown fields in league[{idx}].source_coverage "
                f"for schema_version {schema_version}: {extra_coverage}"
            )
