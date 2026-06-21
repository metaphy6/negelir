"""Phase 19.5 §19.5 — WC qualifier format type definitions and validation."""
from __future__ import annotations

import pytest
from common.schemas.competition import (
    ConfoederationGroup,
    InterConfederationPath,
    QualificationRound,
    WcQualifierFormat,
    CompetitionPayload,
)


class TestWcQualifierFormatTypes:
    """Tests for WC qualifier format type definitions."""

    def test_confederation_group_required_fields(self) -> None:
        """ConfoederationGroup must support required fields."""
        group: ConfoederationGroup = {
            "size": 10,
            "carry_forward_rules": ["seeded_advantage"],
            "automatic_qualifier_slots": 1,
            "playoff_slots": 2,
        }
        assert group["size"] == 10
        assert group["carry_forward_rules"] == ["seeded_advantage"]
        assert group["automatic_qualifier_slots"] == 1
        assert group["playoff_slots"] == 2

    def test_inter_confederation_path_required_fields(self) -> None:
        """InterConfederationPath must support required fields."""
        path: InterConfederationPath = {
            "from_confederation": "UEFA",
            "to_confederation": "CONMEBOL",
            "slot_count": 1,
            "format": "two_leg",
        }
        assert path["from_confederation"] == "UEFA"
        assert path["to_confederation"] == "CONMEBOL"
        assert path["slot_count"] == 1
        assert path["format"] == "two_leg"

    def test_qualification_round_required_fields(self) -> None:
        """QualificationRound must support required fields."""
        round_: QualificationRound = {
            "round_id": "group_stage",
            "format": "group_stage",
            "teams_in": 50,
            "teams_advance": 8,
        }
        assert round_["round_id"] == "group_stage"
        assert round_["format"] == "group_stage"
        assert round_["teams_in"] == 50
        assert round_["teams_advance"] == 8

    def test_wc_qualifier_format_required_fields(self) -> None:
        """WcQualifierFormat must support all required fields."""
        conf_group: ConfoederationGroup = {
            "size": 10,
            "carry_forward_rules": ["seeded_advantage"],
            "automatic_qualifier_slots": 1,
            "playoff_slots": 2,
        }
        inter_path: InterConfederationPath = {
            "from_confederation": "UEFA",
            "to_confederation": "CONMEBOL",
            "slot_count": 1,
            "format": "two_leg",
        }
        round_: QualificationRound = {
            "round_id": "group_stage",
            "format": "group_stage",
            "teams_in": 50,
            "teams_advance": 8,
        }

        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [conf_group],
            "inter_confederation_paths": [inter_path],
            "rounds": [round_],
            "participant_count_range": {"min": 40, "max": 55},
            "qualification_matrix_schema_version": 1,
        }

        assert len(wc_fmt["confederation_groups"]) == 1
        assert len(wc_fmt["inter_confederation_paths"]) == 1
        assert len(wc_fmt["rounds"]) == 1
        assert wc_fmt["participant_count_range"]["min"] == 40
        assert wc_fmt["qualification_matrix_schema_version"] == 1

    def test_competition_payload_supports_wc_qualifier_format(self) -> None:
        """CompetitionPayload must support wc_qualifier format type."""
        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [
                {
                    "size": 10,
                    "carry_forward_rules": ["seeded_advantage"],
                    "automatic_qualifier_slots": 1,
                    "playoff_slots": 2,
                }
            ],
            "inter_confederation_paths": [
                {
                    "from_confederation": "UEFA",
                    "to_confederation": "CONMEBOL",
                    "slot_count": 1,
                    "format": "two_leg",
                }
            ],
            "rounds": [
                {
                    "round_id": "group_stage",
                    "format": "group_stage",
                    "teams_in": 50,
                    "teams_advance": 8,
                }
            ],
            "participant_count_range": {"min": 40, "max": 55},
            "qualification_matrix_schema_version": 1,
        }

        payload: CompetitionPayload = {
            "competition_id": "wc_qualifier_uefa_2026",
            "name_en": "UEFA World Cup 2026 Qualifiers",
            "name_tr": "2026 FIFA Dünya Kupası UEFA Ön Eleme",
            "aliases": ["WC 2026 UEFA Qualifiers"],
            "format": "wc_qualifier",
            "scope": "international_qualifier",
            "default_venue_policy": "home_away",
            "organizer": "FIFA",
            "confederation": "UEFA",
            "countries": ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR"],
            "nationality_restricted": True,
            "calibration_profile_id": "wc_qualifier_group_stage",
            "active": True,
            "wc_qualifier": wc_fmt,
        }

        assert payload["format"] == "wc_qualifier"
        assert payload["wc_qualifier"] is not None
        assert payload["wc_qualifier"]["qualification_matrix_schema_version"] == 1

    def test_inter_confederation_path_accepts_single_leg(self) -> None:
        """InterConfederationPath format field must accept 'single_leg'."""
        path: InterConfederationPath = {
            "from_confederation": "AFC",
            "to_confederation": "OFC",
            "slot_count": 1,
            "format": "single_leg",
        }
        assert path["format"] == "single_leg"

    def test_qualification_round_accepts_two_leg_tie(self) -> None:
        """QualificationRound format field must accept 'two_leg_tie'."""
        round_: QualificationRound = {
            "round_id": "playoff_1",
            "format": "two_leg_tie",
            "teams_in": 8,
            "teams_advance": 4,
        }
        assert round_["format"] == "two_leg_tie"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
