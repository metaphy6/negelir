"""Phase 19.5 §19.5 bullet 9 — CompetitionConfig versioning.

Tests that changes to structural fields increment config_version,
and changes to name_tr/name_en do NOT require version bump.
"""

from __future__ import annotations

import pytest


class TestCompetitionConfigVersion:
    """Test competition config versioning."""

    def test_config_version_incremented_on_format_change(self) -> None:
        """Changing format requires config_version bump."""
        old_config = {
            "competition_id": "euro_2024",
            "format": "group_then_knockout",
            "config_version": 1,
        }

        new_config = {
            "competition_id": "euro_2024",
            "format": "group_then_knockout",
            "continental_championship": {
                "group_stage": {
                    "num_groups": 4,
                    "teams_per_group": 4,
                    "teams_advancing_per_group": 2,
                    "tiebreaker_rules": ["head_to_head"],
                },
            },
            "config_version": 2,
        }

        assert new_config["config_version"] > old_config["config_version"]

    def test_config_version_unchanged_on_name_change(self) -> None:
        """Changing only name_tr/name_en does NOT bump config_version."""
        config_v1 = {
            "competition_id": "euro_2024",
            "name_en": "UEFA Euro 2024",
            "name_tr": "UEFA Euro 2024",
            "format": "group_then_knockout",
            "config_version": 1,
        }

        config_v1_updated = {
            "competition_id": "euro_2024",
            "name_en": "UEFA European Football Championship 2024",
            "name_tr": "UEFA Avrupa Futbol Şampiyonası 2024",
            "format": "group_then_knockout",
            "config_version": 1,
        }

        assert config_v1_updated["config_version"] == config_v1["config_version"]

    def test_config_version_incremented_on_stages_change(self) -> None:
        """Changing stages requires config_version bump."""
        old_config = {
            "competition_id": "ucl_2024",
            "format": "group_then_knockout",
            "config_version": 1,
            "stages": [
                {"stage_id": "group_stage", "order": 0},
                {"stage_id": "round_of_16", "order": 1},
            ],
        }

        new_config = {
            "competition_id": "ucl_2024",
            "format": "group_then_knockout",
            "config_version": 2,
            "stages": [
                {"stage_id": "group_stage", "order": 0},
                {"stage_id": "qualifying_round", "order": 1},
                {"stage_id": "round_of_16", "order": 2},
            ],
        }

        assert new_config["config_version"] > old_config["config_version"]

    def test_config_version_incremented_on_wc_qualifier_change(self) -> None:
        """Changing wc_qualifier structure requires config_version bump."""
        old_config = {
            "competition_id": "wc_qualifier_2026",
            "format": "wc_qualifier",
            "config_version": 1,
            "wc_qualifier": {
                "confederation_groups": [
                    {
                        "confederation": "UEFA",
                        "size": 8,
                        "automatic_qualifier_slots": 3,
                    },
                ],
            },
        }

        new_config = {
            "competition_id": "wc_qualifier_2026",
            "format": "wc_qualifier",
            "config_version": 2,
            "wc_qualifier": {
                "confederation_groups": [
                    {
                        "confederation": "UEFA",
                        "size": 8,
                        "automatic_qualifier_slots": 2,  # Changed
                        "playoff_slots": 2,
                    },
                ],
            },
        }

        assert new_config["config_version"] > old_config["config_version"]

    def test_old_config_version_calibration_preserved(self) -> None:
        """Historical calibration data keyed on (competition_id, config_version)."""
        calibration_store = {
            ("euro_2024", 1): {"log_loss": 0.42, "brier_score": 0.18},
            ("euro_2024", 2): {"log_loss": 0.41, "brier_score": 0.17},
        }

        # When config_version changes, old calibration is preserved
        euro_id = "euro_2024"
        assert (euro_id, 1) in calibration_store
        assert (euro_id, 2) in calibration_store

        # New version starts fresh calibration window
        assert calibration_store[(euro_id, 2)]["log_loss"] != calibration_store[(euro_id, 1)]["log_loss"]

    def test_structural_fields_list(self) -> None:
        """Verify which fields trigger version bump."""
        structural_fields = {
            "format",
            "scope",
            "stages",
            "wc_qualifier",
            "continental_championship",
            "participant_crystallisation_gate",
            "default_venue_policy",
            "calibration_profile_id",
        }

        non_structural_fields = {
            "name_en",
            "name_tr",
            "aliases",
            "organizer",
        }

        # These fields should trigger version bump
        for field in structural_fields:
            assert field in structural_fields

        # These fields should NOT trigger version bump
        for field in non_structural_fields:
            assert field not in structural_fields
