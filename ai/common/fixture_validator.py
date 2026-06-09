"""
Phase 13.2 — Fixture schema-gate validator.

Enforces that fixtures for T1/T2 leagues include required competition fields:
  - competition_id
  - competition_format
  - venue_policy

T3 leagues are allowed to have null values with a warning and metric increment.

Per COMPETITIONS.md §3 and Phase 13.2 checklist: "Schema-gate at ingest."
"""

from __future__ import annotations

from typing import Any, Mapping

from common.logger import get_logger
from common.league_catalog_loader import CATALOG
from common.telemetry import FIXTURE_COMPETITION_MISSING_TOTAL

log = get_logger(__name__)


class FixtureSchemaGateError(Exception):
    """Raised when a T1/T2 fixture is missing required competition fields."""
    pass


def validate_fixture_competition_fields(
    fixture: Mapping[str, Any],
    league_id: str,
) -> None:
    """
    Validate that a fixture has required competition fields based on league tier.

    For T1/T2 leagues: competition_id, competition_format, and venue_policy
    are required (non-null).

    For T3 leagues: null values are allowed with a warning and metric increment.

    Args:
        fixture: The fixture payload (Mapping).
        league_id: The league_id for the fixture.

    Raises:
        FixtureSchemaGateError: If a T1/T2 fixture is missing required fields.
    """
    # Required fields per FixturePayloadV2 (COMPETITIONS.md §3)
    required_fields = {"competition_id", "competition_format", "venue_policy"}

    # Get the league row to check tier
    league_row = CATALOG.get(league_id)
    if not league_row:
        log.warning(
            "Fixture schema-gate: league_id '%s' not in catalog; skipping validation",
            league_id,
        )
        return

    # Check for missing fields
    missing_fields = [
        field for field in required_fields
        if fixture.get(field) is None
    ]

    if not missing_fields:
        # All fields present; pass
        return

    if league_row.tier in ("T1", "T2"):
        # T1/T2 fixtures must have all competition fields
        raise FixtureSchemaGateError(
            f"T{league_row.tier} fixture for league '{league_id}' missing required "
            f"competition fields: {missing_fields}. All of {required_fields} must be non-null."
        )

    elif league_row.tier == "T3":
        # T3 fixtures allow null values; warn and increment metric
        if FIXTURE_COMPETITION_MISSING_TOTAL is not None:
            FIXTURE_COMPETITION_MISSING_TOTAL.labels(league_id=league_id).inc()

        log.warning(
            "T3 fixture for league '%s' missing competition fields: %s "
            "(allowed for T3 with warning)",
            league_id,
            missing_fields,
        )
    else:
        log.warning(
            "Unknown tier '%s' for league '%s'; cannot enforce schema-gate",
            league_row.tier,
            league_id,
        )
