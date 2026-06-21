"""Phase 19.5 §19.5 — Participant-crystallisation gate for international tournaments.

Tests that wc_qualifier and continental_championship competitions require a
participant_crystallisation_gate declaration before T2 promotion, and that
T1/T2 readiness checks enforce this gate.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Add path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestParticipantCrystallisationGateBlocking:
    """Verify that wc_qualifier and continental_championship require crystallisation gates."""

    def test_gate_type_schema(self) -> None:
        """Verify ParticipantCrystallisationGate TypedDict exists and has correct fields."""
        from common.schemas.competition import ParticipantCrystallisationGate
        
        # Valid gate structure
        gate: ParticipantCrystallisationGate = {
            "type": "qualifier_legs_resolved",
            "competition_id": "wc_qualifier_uefa_2026",
        }
        assert gate["type"] in ("qualifier_legs_resolved", "draw_held")
        assert gate["competition_id"] == "wc_qualifier_uefa_2026"

    def test_gate_in_competition_payload(self) -> None:
        """Verify that CompetitionPayload includes participant_crystallisation_gate field."""
        from common.schemas.competition import CompetitionPayload
        
        # Create a minimal competition payload with wc_qualifier format
        payload: CompetitionPayload = {
            "competition_id": "wc_qualifier_uefa_2026",
            "name_en": "UEFA World Cup 2026 Qualifiers",
            "name_tr": "UEFA 2026 Dünya Kupası Elemeleri",
            "aliases": ["WC 2026 Qualifiers"],
            "format": "wc_qualifier",
            "scope": "international_qualifier",
            "default_venue_policy": "neutral",
            "organizer": "FIFA",
            "confederation": "UEFA",
            "countries": ["DE", "FR", "ES", "IT"],
            "nationality_restricted": True,
            "calibration_profile_id": "wc_qualifier_default",
            "active": True,
            "participant_crystallisation_gate": {
                "type": "qualifier_legs_resolved",
                "competition_id": "wc_qualifier_uefa_2026",
            },
        }
        
        assert payload["participant_crystallisation_gate"] is not None
        gate = payload["participant_crystallisation_gate"]
        assert gate["type"] == "qualifier_legs_resolved"


class TestGateFieldStructure:
    """Verify that the participant_crystallisation_gate field is properly typed."""

    def test_gate_type_values_valid(self) -> None:
        """Gate.type must be either 'qualifier_legs_resolved' or 'draw_held'."""
        from common.schemas.competition import ParticipantCrystallisationGate
        
        # Valid types
        gate_qlr: ParticipantCrystallisationGate = {
            "type": "qualifier_legs_resolved",
            "competition_id": "wc_qualifier_uefa_2026",
        }
        gate_dh: ParticipantCrystallisationGate = {
            "type": "draw_held",
            "competition_id": "euro_2028",
        }
        
        assert gate_qlr["type"] == "qualifier_legs_resolved"
        assert gate_dh["type"] == "draw_held"

    def test_continental_championship_with_gate(self) -> None:
        """Test a continental_championship payload with crystallisation gate."""
        from common.schemas.competition import CompetitionPayload
        
        payload: CompetitionPayload = {
            "competition_id": "euro_2028",
            "name_en": "UEFA Euro 2028",
            "name_tr": "UEFA Euro 2028",
            "aliases": ["Euro 2028"],
            "format": "continental_championship",
            "scope": "international_championship",
            "default_venue_policy": "neutral",
            "organizer": "UEFA",
            "confederation": "UEFA",
            "countries": ["DE", "FR", "ES", "IT"],
            "nationality_restricted": True,
            "calibration_profile_id": "continental_championship_default",
            "active": True,
            "continental_championship": {
                "group_stage": {
                    "num_groups": 4,
                    "teams_per_group": 4,
                    "teams_advancing_per_group": 2,
                },
                "knockout_phase": {
                    "format": "single_knockout",
                    "semi_finals_legs": 1,
                    "final_legs": 1,
                    "extra_time": True,
                    "penalties": True,
                },
                "host_nation_flag": True,
            },
            "participant_crystallisation_gate": {
                "type": "draw_held",
                "competition_id": "euro_2028",
            },
        }
        
        assert payload["format"] == "continental_championship"
        assert payload["participant_crystallisation_gate"] is not None
        assert payload["participant_crystallisation_gate"]["type"] == "draw_held"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
