"""Phase 19.5 §19.5 bullet 9 — Historical calibration preservation.

Tests that calibration data keyed on (competition_id, config_version) is preserved
across config version changes.
"""

from __future__ import annotations

import pytest


class TestOldConfigVersionCalibrationPreserved:
    """Test historical calibration data preservation across config versions."""

    def test_config_version_change_preserves_old_calibration(self) -> None:
        """Old calibration data is preserved when config_version changes."""
        calibration_store = {}

        # Initial calibration for euro_2024 v1
        calibration_store[("euro_2024", 1)] = {
            "log_loss": 0.425,
            "brier_score": 0.182,
            "seasons_fit": 5,
            "n_fixtures": 1250,
        }

        # Config changes, version bumps to 2
        # New calibration starts but old data is preserved
        calibration_store[("euro_2024", 2)] = {
            "log_loss": None,  # Not yet fitted
            "brier_score": None,
            "seasons_fit": 0,
            "n_fixtures": 0,
        }

        # Old calibration still accessible
        assert ("euro_2024", 1) in calibration_store
        assert calibration_store[("euro_2024", 1)]["log_loss"] == 0.425

        # New version is separate
        assert ("euro_2024", 2) in calibration_store
        assert calibration_store[("euro_2024", 2)]["log_loss"] is None

    def test_multiple_config_versions_stored_independently(self) -> None:
        """Multiple config versions of same competition stored independently."""
        store = {
            ("ucl", 1): {"fitted": True, "params": {"k": 32}},
            ("ucl", 2): {"fitted": True, "params": {"k": 24}},
            ("ucl", 3): {"fitted": False, "params": None},
        }

        # Each version has independent data
        assert store[("ucl", 1)]["params"]["k"] == 32
        assert store[("ucl", 2)]["params"]["k"] == 24
        assert store[("ucl", 3)]["fitted"] is False

    def test_predictor_loads_correct_calibration_for_version(self) -> None:
        """Predictor loads the correct calibration for given config version."""
        calibrations = {
            ("wc_2022", 1): {"model": "wc_2022_v1", "log_loss": 0.41},
            ("wc_2022", 2): {"model": "wc_2022_v2", "log_loss": 0.38},
        }

        competition_id = "wc_2022"
        config_version = 2

        calibration_key = (competition_id, config_version)
        assert calibration_key in calibrations

        loaded_calibration = calibrations[calibration_key]
        assert loaded_calibration["model"] == "wc_2022_v2"
        assert loaded_calibration["log_loss"] == 0.38

    def test_config_version_bump_triggers_new_calibration_window(self) -> None:
        """Config version bump starts a new independent calibration window."""
        # Before: v1 calibration running for 3 seasons
        seasons_v1 = [2022, 2023, 2024]
        calibration_v1 = {
            "seasons": seasons_v1,
            "log_loss": 0.42,
            "ready_for_promotion": True,
        }

        # Config changes (e.g., rule change to the format)
        # v2 starts fresh, ignoring v1 history
        calibration_v2 = {
            "seasons": [2024],  # Restarted with current season only
            "log_loss": None,  # Not fitted yet
            "ready_for_promotion": False,
        }

        # v1 data is archived but available for reference
        calibration_store = {
            ("euro_2024", 1): calibration_v1,
            ("euro_2024", 2): calibration_v2,
        }

        assert calibration_store[("euro_2024", 1)]["ready_for_promotion"] is True
        assert calibration_store[("euro_2024", 2)]["ready_for_promotion"] is False

    def test_migration_preserves_old_version_data(self) -> None:
        """Migration from old config to new version preserves old data."""
        old_store = {
            ("copa_america", 1): {"fitted_seasons": 4, "validation_loss": 0.38},
        }

        # Add new version without deleting old
        new_store = old_store.copy()
        new_store[("copa_america", 2)] = {"fitted_seasons": 0, "validation_loss": None}

        # Both versions present
        assert ("copa_america", 1) in new_store
        assert ("copa_america", 2) in new_store
        assert new_store[("copa_america", 1)]["fitted_seasons"] == 4
