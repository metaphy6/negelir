"""
Phase 13.2 — Fixture schema-gate validator tests.

Tests for the FixtureSchemaGateError enforcement:
  - T1/T2 fixtures with missing fields raise errors
  - T3 fixtures with missing fields warn but don't error
  - Fixtures with all fields pass
  - Metrics are incremented for T3 missing fields
"""

import pytest
from unittest.mock import MagicMock, patch

from ai.common.fixture_validator import (
    FixtureSchemaGateError,
    validate_fixture_competition_fields,
)


class TestFixtureSchemaGate:
    """Tests for fixture competition field validation."""

    def test_fixture_with_all_required_fields_passes(self):
        """Happy path: fixture with all required competition fields passes."""
        fixture = {
            "competition_id": "super_lig",
            "competition_format": "round_robin",
            "venue_policy": "home_away",
            "home_team": "Galatasaray",
            "away_team": "Fenerbahce",
        }
        # Should not raise
        validate_fixture_competition_fields(fixture, "tr_super_lig")

    def test_t1_fixture_missing_competition_id_raises_error(self):
        """T1 fixture missing competition_id raises FixtureSchemaGateError."""
        fixture = {
            "competition_format": "round_robin",
            "venue_policy": "home_away",
            "home_team": "Galatasaray",
            "away_team": "Fenerbahce",
        }
        with pytest.raises(FixtureSchemaGateError) as exc_info:
            validate_fixture_competition_fields(fixture, "tr_super_lig")
        assert "missing required" in str(exc_info.value)
        assert "competition_id" in str(exc_info.value)

    def test_t1_fixture_missing_competition_format_raises_error(self):
        """T1 fixture missing competition_format raises FixtureSchemaGateError."""
        fixture = {
            "competition_id": "super_lig",
            "venue_policy": "home_away",
            "home_team": "Galatasaray",
            "away_team": "Fenerbahce",
        }
        with pytest.raises(FixtureSchemaGateError) as exc_info:
            validate_fixture_competition_fields(fixture, "tr_super_lig")
        assert "missing required" in str(exc_info.value)
        assert "competition_format" in str(exc_info.value)

    def test_t1_fixture_missing_venue_policy_raises_error(self):
        """T1 fixture missing venue_policy raises FixtureSchemaGateError."""
        fixture = {
            "competition_id": "super_lig",
            "competition_format": "round_robin",
            "home_team": "Galatasaray",
            "away_team": "Fenerbahce",
        }
        with pytest.raises(FixtureSchemaGateError) as exc_info:
            validate_fixture_competition_fields(fixture, "tr_super_lig")
        assert "missing required" in str(exc_info.value)
        assert "venue_policy" in str(exc_info.value)

    @patch("ai.common.fixture_validator.FIXTURE_COMPETITION_MISSING_TOTAL")
    def test_t3_fixture_missing_fields_warns_and_increments_metric(self, mock_metric):
        """T3 fixture missing fields warns but doesn't error; metric incremented."""
        fixture = {
            "competition_format": "round_robin",
            # missing competition_id and venue_policy
            "home_team": "Team A",
            "away_team": "Team B",
        }
        # Mock a T3 league
        with patch("ai.common.fixture_validator.CATALOG") as mock_catalog:
            from dataclasses import dataclass
            from typing import FrozenSet

            @dataclass(frozen=True)
            class MockLeagueRow:
                league_id: str
                tier: str
                name_en: str
                name_tr: str
                country: str
                confederation: str
                active_since: str
                competitions: FrozenSet[str]
                source_coverage: object

            mock_row = MockLeagueRow(
                league_id="test_t3",
                tier="T3",
                name_en="Test T3 League",
                name_tr="Test T3 Ligi",
                country="XX",
                confederation="FIFA",
                active_since="2020",
                competitions=frozenset(),
                source_coverage=None,
            )
            mock_catalog.get.return_value = mock_row

            # Should not raise (T3 allows null)
            validate_fixture_competition_fields(fixture, "test_t3")

            # Metric should be incremented
            mock_metric.labels.assert_called_with(league_id="test_t3")
            mock_metric.labels.return_value.inc.assert_called_once()

    @patch("ai.common.fixture_validator.CATALOG")
    def test_unknown_league_skips_validation(self, mock_catalog):
        """Fixture for unknown league_id skips validation (returns early)."""
        fixture = {
            # missing all fields
            "home_team": "Team A",
            "away_team": "Team B",
        }
        mock_catalog.get.return_value = None

        # Should not raise, should skip
        validate_fixture_competition_fields(fixture, "unknown_league")
        mock_catalog.get.assert_called_once_with("unknown_league")

    def test_fixture_with_null_competition_id_is_invalid(self):
        """Fixture with None competition_id (not missing key) is invalid for T1/T2."""
        fixture = {
            "competition_id": None,
            "competition_format": "round_robin",
            "venue_policy": "home_away",
            "home_team": "Galatasaray",
            "away_team": "Fenerbahce",
        }
        with pytest.raises(FixtureSchemaGateError) as exc_info:
            validate_fixture_competition_fields(fixture, "tr_super_lig")
        assert "missing required" in str(exc_info.value)
        assert "competition_id" in str(exc_info.value)

    def test_t2_fixture_missing_fields_raises_error(self):
        """T2 fixture missing fields raises error (same as T1)."""
        fixture = {
            "competition_id": "some_comp",
            # missing competition_format and venue_policy
            "home_team": "Team A",
            "away_team": "Team B",
        }
        with patch("ai.common.fixture_validator.CATALOG") as mock_catalog:
            from dataclasses import dataclass
            from typing import FrozenSet

            @dataclass(frozen=True)
            class MockLeagueRow:
                league_id: str
                tier: str
                name_en: str
                name_tr: str
                country: str
                confederation: str
                active_since: str
                competitions: FrozenSet[str]
                source_coverage: object

            mock_row = MockLeagueRow(
                league_id="test_t2",
                tier="T2",
                name_en="Test T2 League",
                name_tr="Test T2 Ligi",
                country="XX",
                confederation="FIFA",
                active_since="2020",
                competitions=frozenset(),
                source_coverage=None,
            )
            mock_catalog.get.return_value = mock_row

            with pytest.raises(FixtureSchemaGateError) as exc_info:
                validate_fixture_competition_fields(fixture, "test_t2")
            assert "T2" in str(exc_info.value)
            assert "missing required" in str(exc_info.value)
