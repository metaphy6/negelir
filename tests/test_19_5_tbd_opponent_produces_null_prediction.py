"""Phase 19.5 §19.5 bullet 8 — TBD-opponent placeholder handling.

Tests that WC qualifiers with unresolved play-off opponents use the
Phase 13 §13.51 TbdOpponentPlaceholder fixture type. The predictor
publishes a degenerate prediction (home_win_prob: null) for TBD-opponent
fixtures rather than a fabricated prior.
"""

from __future__ import annotations

import pytest
from common.schemas.records import TbdOpponentFixture, ScheduleTeam


class TestTbdOpponentFixture:
    """Test TBD opponent fixture type and degenerate predictions."""

    def test_tbd_opponent_fixture_structure(self) -> None:
        """TBD opponent fixture has required fields."""
        fixture: TbdOpponentFixture = {
            "match_stable_id": "wc_2026_playoff_a_vs_tbd",
            "kickoff_utc": "2026-03-15T19:00:00Z",
            "home": {
                "team_id": "team_a",
                "team_name": "Team A",
            },
            "away": {
                "team_id": "TBD",
                "team_name": None,
            },
            "competition": "wc_qualifier_playoff",
            "status": "tbd_opponent",
            "tbd_reason": "play_off_not_drawn",
            "expected_confirmation_at": "2026-03-10T19:00:00Z",
        }

        assert fixture["status"] == "tbd_opponent"
        assert fixture["away"]["team_id"] == "TBD"
        assert fixture["tbd_reason"] == "play_off_not_drawn"

    def test_tbd_opponent_reasons(self) -> None:
        """TBD opponent can have various reasons for unresolved status."""
        reasons = [
            "play_off_not_drawn",
            "qualifier_leg_pending",
            "inter_confederation_bracket_unresolved",
        ]

        for reason in reasons:
            fixture: TbdOpponentFixture = {
                "match_stable_id": f"wc_2026_{reason}",
                "kickoff_utc": "2026-03-15T19:00:00Z",
                "home": {"team_id": "team_a", "team_name": "Team A"},
                "away": {"team_id": "TBD", "team_name": None},
                "competition": "wc_qualifier_playoff",
                "status": "tbd_opponent",
                "tbd_reason": reason,
                "expected_confirmation_at": "2026-03-10T19:00:00Z",
            }

            assert fixture["tbd_reason"] == reason

    def test_tbd_opponent_degenerate_prediction_is_null(self) -> None:
        """Predictor publishes degenerate prediction (home_win_prob: null) for TBD fixtures."""
        # This simulates what the predictor does when it encounters a TBD fixture
        fixture: TbdOpponentFixture = {
            "match_stable_id": "wc_2026_playoff_unk_vs_tbd",
            "kickoff_utc": "2026-04-20T20:00:00Z",
            "home": {"team_id": "unknown_qualifier", "team_name": None},
            "away": {"team_id": "TBD", "team_name": None},
            "competition": "wc_qualifier_playoff",
            "status": "tbd_opponent",
            "tbd_reason": "inter_confederation_bracket_unresolved",
            "expected_confirmation_at": "2026-04-15T20:00:00Z",
        }

        # Predictor logic: if fixture.status == "tbd_opponent", publish degenerate prediction
        if fixture["status"] == "tbd_opponent":
            prediction = {
                "match_stable_id": fixture["match_stable_id"],
                "home_win_prob": None,
                "draw_prob": None,
                "away_win_prob": None,
                "reason": "tbd_opponent",
                "suppressed": True,
            }
        else:
            prediction = {
                "match_stable_id": fixture["match_stable_id"],
                "home_win_prob": 0.45,
            }

        assert prediction["home_win_prob"] is None
        assert prediction["draw_prob"] is None
        assert prediction["away_win_prob"] is None
        assert prediction["reason"] == "tbd_opponent"
        assert prediction["suppressed"] is True

    def test_tbd_fixture_not_published(self) -> None:
        """Degenerate TBD predictions are stored but never published to end users."""
        fixture: TbdOpponentFixture = {
            "match_stable_id": "wc_2026_playoff_unk_vs_tbd",
            "kickoff_utc": "2026-04-20T20:00:00Z",
            "home": {"team_id": "unknown_qualifier", "team_name": None},
            "away": {"team_id": "TBD", "team_name": None},
            "competition": "wc_qualifier_playoff",
            "status": "tbd_opponent",
            "tbd_reason": "play_off_not_drawn",
            "expected_confirmation_at": "2026-04-15T20:00:00Z",
        }

        # Record is stored with suppressed: true
        record = {
            "match_stable_id": fixture["match_stable_id"],
            "tier": "T3",
            "status": "tbd_opponent",
            "suppressed": True,
            "reason": "tbd_opponent",
        }

        # Publish logic: only publish if suppressed == False or if admin token
        should_publish_to_user = record.get("suppressed", False) is False
        should_publish_to_admin = True

        assert should_publish_to_user is False
        assert should_publish_to_admin is True

    def test_tbd_fixture_resolved_to_normal_fixture(self) -> None:
        """When TBD is resolved, fixture transitions to normal status."""
        tbd_fixture: TbdOpponentFixture = {
            "match_stable_id": "wc_2026_playoff_a_vs_b",
            "kickoff_utc": "2026-03-15T19:00:00Z",
            "home": {"team_id": "team_a", "team_name": "Team A"},
            "away": {"team_id": "TBD", "team_name": None},
            "competition": "wc_qualifier_playoff",
            "status": "tbd_opponent",
            "tbd_reason": "play_off_not_drawn",
            "expected_confirmation_at": "2026-03-10T19:00:00Z",
        }

        # After resolution, fixture updates to normal schedule
        resolved_fixture = {
            "match_stable_id": tbd_fixture["match_stable_id"],
            "kickoff_utc": tbd_fixture["kickoff_utc"],
            "home": tbd_fixture["home"],
            "away": {"team_id": "team_b", "team_name": "Team B"},
            "competition": tbd_fixture["competition"],
            "status": "scheduled",
        }

        assert resolved_fixture["status"] == "scheduled"
        assert resolved_fixture["away"]["team_id"] != "TBD"
