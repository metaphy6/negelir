"""Phase 19.5 §19.5 — Multi-round WC qualifier format support."""
from __future__ import annotations

import pytest
from common.schemas.competition import (
    ConfoederationGroup,
    InterConfederationPath,
    QualificationRound,
    WcQualifierFormat,
    CompetitionPayload,
)


class TestWcQualifierMultiRound:
    """Tests for multi-round WC qualifier format support (UEFA 3-round, CONMEBOL single-round, etc.)."""

    def test_conmebol_single_group_format(self) -> None:
        """CONMEBOL uses a single 10-team group with all teams advancing to playoffs."""
        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [
                {
                    "size": 10,
                    "carry_forward_rules": [],
                    "automatic_qualifier_slots": 4,
                    "playoff_slots": 1,
                }
            ],
            "inter_confederation_paths": [
                {
                    "from_confederation": "CONMEBOL",
                    "to_confederation": "FIFA",
                    "slot_count": 1,
                    "format": "single_leg",
                }
            ],
            "rounds": [
                {
                    "round_id": "group_stage",
                    "format": "group_stage",
                    "teams_in": 10,
                    "teams_advance": 5,
                }
            ],
            "participant_count_range": {"min": 10, "max": 10},
            "qualification_matrix_schema_version": 1,
        }

        assert len(wc_fmt["confederation_groups"]) == 1
        assert len(wc_fmt["rounds"]) == 1
        assert wc_fmt["rounds"][0]["round_id"] == "group_stage"

    def test_uefa_three_round_format(self) -> None:
        """UEFA uses 3 rounds: groups → playoff round → inter-confederation playoff."""
        group_stage_round: QualificationRound = {
            "round_id": "group_stage",
            "format": "group_stage",
            "teams_in": 55,
            "teams_advance": 16,  # 10 winners + 6 best runners-up
        }
        playoff_round: QualificationRound = {
            "round_id": "playoff_round",
            "format": "two_leg_tie",
            "teams_in": 16,
            "teams_advance": 13,
        }
        inter_conf_round: QualificationRound = {
            "round_id": "inter_confederation",
            "format": "two_leg_tie",
            "teams_in": 1,  # Adjusted per inter-confederation paths
            "teams_advance": 1,
        }

        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [
                {
                    "size": 5,
                    "carry_forward_rules": ["seeded_advantage"],
                    "automatic_qualifier_slots": 2,
                    "playoff_slots": 1,
                }
            ] * 11,  # 11 groups in UEFA
            "inter_confederation_paths": [
                {
                    "from_confederation": "UEFA",
                    "to_confederation": "FIFA",
                    "slot_count": 4,
                    "format": "single_leg",
                }
            ],
            "rounds": [group_stage_round, playoff_round, inter_conf_round],
            "participant_count_range": {"min": 55, "max": 55},
            "qualification_matrix_schema_version": 1,
        }

        assert len(wc_fmt["confederation_groups"]) == 11
        assert len(wc_fmt["rounds"]) == 3
        assert wc_fmt["rounds"][0]["round_id"] == "group_stage"
        assert wc_fmt["rounds"][1]["round_id"] == "playoff_round"
        assert wc_fmt["rounds"][2]["round_id"] == "inter_confederation"

    def test_caf_two_round_format(self) -> None:
        """CAF uses 2 rounds: qualification group stage → group stage."""
        round1: QualificationRound = {
            "round_id": "qualification_group",
            "format": "group_stage",
            "teams_in": 40,
            "teams_advance": 10,
        }
        round2: QualificationRound = {
            "round_id": "final_group",
            "format": "group_stage",
            "teams_in": 10,
            "teams_advance": 5,
        }

        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [
                {
                    "size": 4,
                    "carry_forward_rules": [],
                    "automatic_qualifier_slots": 1,
                    "playoff_slots": 0,
                }
            ] * 10,  # 10 groups
            "inter_confederation_paths": [],
            "rounds": [round1, round2],
            "participant_count_range": {"min": 40, "max": 40},
            "qualification_matrix_schema_version": 1,
        }

        assert len(wc_fmt["confederation_groups"]) == 10
        assert len(wc_fmt["rounds"]) == 2

    def test_afc_four_round_format(self) -> None:
        """AFC uses 4 rounds: Round 1 → Round 2 → Round 3 → Playoff."""
        rounds: list[QualificationRound] = [
            {
                "round_id": "round_1",
                "format": "group_stage",
                "teams_in": 40,
                "teams_advance": 20,
            },
            {
                "round_id": "round_2",
                "format": "group_stage",
                "teams_in": 20,
                "teams_advance": 12,
            },
            {
                "round_id": "round_3",
                "format": "group_stage",
                "teams_in": 12,
                "teams_advance": 8,
            },
            {
                "round_id": "playoff",
                "format": "two_leg_tie",
                "teams_in": 8,
                "teams_advance": 4,
            },
        ]

        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [
                {
                    "size": 4,
                    "carry_forward_rules": [],
                    "automatic_qualifier_slots": 1,
                    "playoff_slots": 0,
                }
            ],
            "inter_confederation_paths": [
                {
                    "from_confederation": "AFC",
                    "to_confederation": "FIFA",
                    "slot_count": 4,
                    "format": "single_leg",
                }
            ],
            "rounds": rounds,
            "participant_count_range": {"min": 40, "max": 46},
            "qualification_matrix_schema_version": 1,
        }

        assert len(wc_fmt["rounds"]) == 4
        assert wc_fmt["rounds"][0]["round_id"] == "round_1"
        assert wc_fmt["rounds"][-1]["round_id"] == "playoff"

    def test_competition_payload_with_three_round_wc_qualifier(self) -> None:
        """Full CompetitionPayload for UEFA 3-round WC qualifier."""
        wc_fmt: WcQualifierFormat = {
            "confederation_groups": [
                {
                    "size": 5,
                    "carry_forward_rules": ["seeded_advantage"],
                    "automatic_qualifier_slots": 2,
                    "playoff_slots": 1,
                }
            ] * 11,
            "inter_confederation_paths": [
                {
                    "from_confederation": "UEFA",
                    "to_confederation": "FIFA",
                    "slot_count": 4,
                    "format": "single_leg",
                }
            ],
            "rounds": [
                {
                    "round_id": "group_stage",
                    "format": "group_stage",
                    "teams_in": 55,
                    "teams_advance": 16,
                },
                {
                    "round_id": "playoff_round",
                    "format": "two_leg_tie",
                    "teams_in": 16,
                    "teams_advance": 13,
                },
                {
                    "round_id": "inter_confederation",
                    "format": "two_leg_tie",
                    "teams_in": 1,
                    "teams_advance": 1,
                },
            ],
            "participant_count_range": {"min": 55, "max": 55},
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
        assert len(payload["wc_qualifier"]["rounds"]) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
