"""Phase 19.5 §19.5 bullet 10 — Provisional fixture calendar ingestion.

International tournaments announce their full match schedule 6–18 months in advance.
This importer ingests pre-announced schedules into the Schedule plane with status:provisional;
provisional fixtures are served by the API with a provisional: true flag and excluded from
predictor training until status changes to confirmed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, TypedDict


class ScheduleTeam(TypedDict):
    """Team record in fixture."""
    team_id: str
    team_name: Optional[str]


class ProvisionalFixture(TypedDict):
    """Provisional fixture record."""
    match_stable_id: str
    kickoff_utc: str
    home: ScheduleTeam
    away: ScheduleTeam
    competition: str
    status: str
    provisional: bool
    announced_at: str
    expected_confirmation_at: Optional[str]


@dataclass
class ProvisionalFixtureBatch:
    """A batch of provisional fixtures ingested from a pre-announced tournament schedule."""

    competition_id: str
    """Competition ID (e.g., 'wc_2026', 'euro_2024')."""

    source_url: str
    """Source URL or data origin."""

    fixtures: list[ProvisionalFixture]
    """Ingested fixtures."""

    ingested_at: str
    """ISO-8601 UTC timestamp of ingestion."""

    total_count: int
    """Total number of fixtures ingested."""

    skipped_count: int
    """Number of fixtures skipped (e.g., due to validation errors)."""

    errors: list[str]
    """Validation or ingestion errors encountered."""


def ingest_provisional_fixtures(
    competition_id: str,
    source_data: list[dict],
    source_url: str = "",
) -> ProvisionalFixtureBatch:
    """Ingest a batch of provisional fixtures from pre-announced tournament schedule.

    Args:
        competition_id: Competition ID (e.g., 'wc_2026', 'euro_2024').
        source_data: List of fixture dicts with keys:
            - 'kickoff_utc': ISO-8601 UTC timestamp
            - 'home_team_id': Team ID
            - 'away_team_id': Team ID
            - 'home_team_name': Optional display name
            - 'away_team_name': Optional display name
            - 'announced_at': ISO-8601 UTC when fixture was announced
            - 'expected_confirmation_at': Optional ISO-8601 UTC when provisional status expected to be confirmed
        source_url: Source URL or data origin (for audit trail).

    Returns:
        ProvisionalFixtureBatch with ingested fixtures, error count, and error messages.
    """
    fixtures: list[ProvisionalFixture] = []
    errors: list[str] = []
    skipped_count = 0
    ingested_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for i, item in enumerate(source_data):
        try:
            # Validate required fields
            if not all(k in item for k in ("kickoff_utc", "home_team_id", "away_team_id", "announced_at")):
                errors.append(f"Fixture {i}: missing required field")
                skipped_count += 1
                continue

            # Generate stable ID from competition and fixture data
            match_stable_id = (
                f"{competition_id}_{item['home_team_id']}_{item['away_team_id']}_{item['kickoff_utc'][:10]}"
            )

            fixture: ProvisionalFixture = {
                "match_stable_id": match_stable_id,
                "kickoff_utc": item["kickoff_utc"],
                "home": {
                    "team_id": item["home_team_id"],
                    "team_name": item.get("home_team_name"),
                },
                "away": {
                    "team_id": item["away_team_id"],
                    "team_name": item.get("away_team_name"),
                },
                "competition": competition_id,
                "status": "provisional",
                "provisional": True,
                "announced_at": item["announced_at"],
                "expected_confirmation_at": item.get("expected_confirmation_at"),
            }
            fixtures.append(fixture)
        except Exception as e:
            errors.append(f"Fixture {i}: {str(e)}")
            skipped_count += 1

    return ProvisionalFixtureBatch(
        competition_id=competition_id,
        source_url=source_url,
        fixtures=fixtures,
        ingested_at=ingested_at,
        total_count=len(source_data),
        skipped_count=skipped_count,
        errors=errors,
    )


def mark_fixture_confirmed(
    fixture: ProvisionalFixture,
) -> ProvisionalFixture:
    """Mark a provisional fixture as confirmed.

    Args:
        fixture: ProvisionalFixture to confirm.

    Returns:
        Updated fixture with status: confirmed and provisional: False.
    """
    confirmed = fixture.copy()
    confirmed["status"] = "confirmed"
    confirmed["provisional"] = False
    return confirmed


def filter_provisional_fixtures(fixtures: list[dict]) -> list[dict]:
    """Filter out provisional fixtures from a schedule list.

    Used by the predictor to exclude provisional fixtures from training data.

    Args:
        fixtures: List of fixture records (may contain provisional).

    Returns:
        Filtered list with provisional fixtures removed.
    """
    return [f for f in fixtures if not f.get("provisional", False)]
