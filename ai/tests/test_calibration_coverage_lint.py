"""Test calibration profile coverage linter.

Per COMPETITIONS.md §4 and Phase 13.2 DoD: verify that the linter correctly
detects coverage gaps and ensures all required format/venue_policy pairs
have at least one profile.
"""

import sys
from pathlib import Path

import pytest

# Add xops to path for linter import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "xops"))

from lint.calibration_coverage import (
    lint_calibration_coverage,
    compute_actual_coverage,
    REQUIRED_COVERAGE,
    VALID_FORMATS,
    VALID_VENUE_POLICIES,
)


class TestCalibrationCoverageLint:
    """Tests for calibration profile coverage linter."""

    def test_linter_passes(self) -> None:
        """Linter should report complete coverage."""
        assert lint_calibration_coverage() is True

    def test_all_required_pairs_covered(self) -> None:
        """All required format/venue_policy pairs must have at least one profile."""
        coverage = compute_actual_coverage()
        missing = REQUIRED_COVERAGE - coverage
        assert not missing, (
            f"Missing profiles for: {sorted(missing)}. "
            "Each pair must be covered by at least one calibration profile."
        )

    def test_coverage_size_reasonable(self) -> None:
        """Coverage should include most (format, venue_policy) combinations."""
        coverage = compute_actual_coverage()
        # Should cover at least 15 of the potential pairs
        assert len(coverage) >= 15

    def test_valid_format_values(self) -> None:
        """All formats in coverage must be in VALID_FORMATS."""
        coverage = compute_actual_coverage()
        for fmt, _ in coverage:
            assert fmt in VALID_FORMATS, f"Unknown format: {fmt}"

    def test_valid_venue_policy_values(self) -> None:
        """All venue policies in coverage must be in VALID_VENUE_POLICIES."""
        coverage = compute_actual_coverage()
        for _, venue in coverage:
            assert (
                venue in VALID_VENUE_POLICIES
            ), f"Unknown venue policy: {venue}"

    def test_round_robin_covered(self) -> None:
        """Round-robin format must be covered (baseline league play)."""
        coverage = compute_actual_coverage()
        assert ("round_robin", "home_away") in coverage

    def test_final_only_covered(self) -> None:
        """Final-only format must be covered (super cups)."""
        coverage = compute_actual_coverage()
        assert any(fmt == "final_only" for fmt, _ in coverage)

    def test_knockout_formats_covered(self) -> None:
        """Single and two-leg knockout formats must be covered."""
        coverage = compute_actual_coverage()
        assert any(fmt == "single_knockout" for fmt, _ in coverage)
        assert any(fmt == "two_leg_knockout" for fmt, _ in coverage)

    def test_group_stage_covered(self) -> None:
        """Group round-robin format must be covered."""
        coverage = compute_actual_coverage()
        assert any(fmt == "group_round_robin" for fmt, _ in coverage)

    def test_neutral_venue_policy_covered(self) -> None:
        """Neutral venue policy must be covered by at least one format."""
        coverage = compute_actual_coverage()
        assert any(venue == "neutral" for _, venue in coverage)

    def test_bubble_venue_policy_covered(self) -> None:
        """Bubble venue policy must be covered (COVID-era tournaments)."""
        coverage = compute_actual_coverage()
        assert any(venue == "bubble" for _, venue in coverage)
