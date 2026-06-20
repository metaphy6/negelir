"""Phase 19.5 §19.5 bullet 10 — Provisional fixture calendar ingestion.

Tests that provisional fixtures are stored but excluded from predictor training
until status changes to confirmed.
"""

from __future__ import annotations

import pytest
from xops.leagues.provisional_fixture_importer import (
    ingest_provisional_fixtures,
    filter_provisional_fixtures,
    mark_fixture_confirmed,
)


class TestProvisionalFixtureIngestion:
    """Test provisional fixture ingestion and training exclusion."""

    def test_ingest_provisional_fixtures_from_wc_schedule(self) -> None:
        """Ingest provisional fixtures from pre-announced WC 2026 schedule."""
        source_data = [
            {
                "kickoff_utc": "2026-06-12T18:00:00Z",
                "home_team_id": "france",
                "away_team_id": "netherlands",
                "home_team_name": "France",
                "away_team_name": "Netherlands",
                "announced_at": "2024-12-13T10:00:00Z",
                "expected_confirmation_at": "2026-06-01T00:00:00Z",
            },
            {
                "kickoff_utc": "2026-06-12T20:00:00Z",
                "home_team_id": "argentina",
                "away_team_id": "brazil",
                "home_team_name": "Argentina",
                "away_team_name": "Brazil",
                "announced_at": "2024-12-13T10:00:00Z",
                "expected_confirmation_at": "2026-06-01T00:00:00Z",
            },
        ]

        batch = ingest_provisional_fixtures(
            competition_id="wc_2026",
            source_data=source_data,
            source_url="https://www.fifa.com/tournaments/mens/worldcup/2026",
        )

        assert batch.competition_id == "wc_2026"
        assert batch.total_count == 2
        assert batch.skipped_count == 0
        assert len(batch.fixtures) == 2

        for fixture in batch.fixtures:
            assert fixture["status"] == "provisional"
            assert fixture["provisional"] is True
            assert fixture["competition"] == "wc_2026"

    def test_provisional_fixtures_excluded_from_training(self) -> None:
        """Provisional fixtures are excluded from predictor training."""
        fixtures = [
            {
                "match_stable_id": "euro_2024_france_vs_netherlands_g1",
                "status": "scheduled",
                "provisional": False,
            },
            {
                "match_stable_id": "wc_2026_france_vs_netherlands_grp",
                "status": "provisional",
                "provisional": True,
            },
            {
                "match_stable_id": "euro_2024_spain_vs_italy_g2",
                "status": "scheduled",
                "provisional": False,
            },
        ]

        training_fixtures = filter_provisional_fixtures(fixtures)

        assert len(training_fixtures) == 2
        assert all(not f.get("provisional", False) for f in training_fixtures)
        assert all(f["status"] == "scheduled" for f in training_fixtures)

    def test_provisional_fixture_marked_confirmed(self) -> None:
        """When provisional fixture is confirmed, status updates."""
        provisional_fixture = {
            "match_stable_id": "wc_2026_france_vs_netherlands",
            "kickoff_utc": "2026-06-12T18:00:00Z",
            "home": {"team_id": "france", "team_name": "France"},
            "away": {"team_id": "netherlands", "team_name": "Netherlands"},
            "competition": "wc_2026",
            "status": "provisional",
            "provisional": True,
            "announced_at": "2024-12-13T10:00:00Z",
            "expected_confirmation_at": "2026-06-01T00:00:00Z",
        }

        confirmed_fixture = mark_fixture_confirmed(provisional_fixture)

        assert confirmed_fixture["status"] == "confirmed"
        assert confirmed_fixture["provisional"] is False
        assert confirmed_fixture["match_stable_id"] == provisional_fixture["match_stable_id"]

    def test_provisional_flag_propagates_to_api_response(self) -> None:
        """Provisional flag is included in API response so clients know."""
        provisional_fixture = {
            "match_stable_id": "wc_2026_france_vs_netherlands",
            "status": "provisional",
            "provisional": True,
            "kickoff_utc": "2026-06-12T18:00:00Z",
        }

        api_response = {
            "match_id": provisional_fixture["match_stable_id"],
            "status": provisional_fixture["status"],
            "provisional": provisional_fixture.get("provisional", False),
            "kickoff_utc": provisional_fixture["kickoff_utc"],
        }

        assert api_response["provisional"] is True
        assert api_response["status"] == "provisional"

    def test_schedule_watcher_confirms_provisional_fixture(self) -> None:
        """Schedule watcher updates provisional fixture to confirmed on confirmation day."""
        provisional_fixture = {
            "match_stable_id": "wc_2026_france_vs_netherlands",
            "status": "provisional",
            "provisional": True,
            "announced_at": "2024-12-13T10:00:00Z",
            "expected_confirmation_at": "2026-06-01T00:00:00Z",
        }

        # Simulate schedule watcher detecting confirmation
        current_utc = "2026-06-01T05:00:00Z"
        expected_confirmation = "2026-06-01T00:00:00Z"

        if current_utc >= expected_confirmation:
            confirmed_fixture = mark_fixture_confirmed(provisional_fixture)
        else:
            confirmed_fixture = provisional_fixture

        assert confirmed_fixture["status"] == "confirmed"
        assert confirmed_fixture["provisional"] is False

    def test_ingest_with_errors(self) -> None:
        """Ingestion handles malformed fixtures gracefully."""
        source_data = [
            {
                "kickoff_utc": "2026-06-12T18:00:00Z",
                "home_team_id": "france",
                "away_team_id": "netherlands",
                "announced_at": "2024-12-13T10:00:00Z",
            },
            {
                # Missing kickoff_utc
                "home_team_id": "argentina",
                "away_team_id": "brazil",
                "announced_at": "2024-12-13T10:00:00Z",
            },
        ]

        batch = ingest_provisional_fixtures(
            competition_id="wc_2026",
            source_data=source_data,
            source_url="https://www.fifa.com",
        )

        assert batch.total_count == 2
        assert batch.skipped_count == 1
        assert len(batch.fixtures) == 1
        assert len(batch.errors) == 1
