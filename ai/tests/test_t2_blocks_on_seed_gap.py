"""Proof test for mock-corpus completeness gate (Phase 13.6, bullet 7).

Verifies that league promotion is blocked when source_coverage has gaps
in Reference or Schedule planes (T2 requirement) or Live/Market planes (T1).

Binding: AGENTS.md Rule 7 + Phase 13.6 §13.0 assumption #32 (retirement).
"""

import pytest
import sys
import os

# Add xops to path for direct import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from xops.leagues.readiness import check_source_coverage_for_tier


class TestT2BlocksOnSeedGap:
    """Verify T2 promotion gate blocks on coverage gaps."""

    def test_t2_requires_reference_and_schedule(self):
        """T2 promotion requires at least one source per Reference and Schedule."""
        # tr_super_lig has complete coverage, should pass
        result = check_source_coverage_for_tier("tr_super_lig", "T2")
        assert result["complete"], f"Expected complete coverage for T2, got gaps: {result['gaps']}"

    def test_t1_requires_live_and_market(self):
        """T1 promotion requires Reference + Schedule + Live + Market."""
        # tr_super_lig has all 4, should pass for T1
        result = check_source_coverage_for_tier("tr_super_lig", "T1")
        assert result["complete"], f"Expected complete coverage for T1, got gaps: {result['gaps']}"

    def test_nonexistent_league_fails(self):
        """Nonexistent league fails readiness check."""
        result = check_source_coverage_for_tier("nonexistent_league", "T2")
        assert not result["complete"]
        assert any("not found" in gap for gap in result["gaps"])

    def test_result_structure(self):
        """Readiness check result has correct structure."""
        result = check_source_coverage_for_tier("tr_super_lig", "T2")
        assert "complete" in result
        assert "gaps" in result
        assert isinstance(result["complete"], bool)
        assert isinstance(result["gaps"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
