"""Phase 18.3 — Tests for shim deletion pre-conditions (three signals).

Validates that the shim deletion gates require three independent signals:
1. Zero CI DeprecationWarnings
2. Zero production runtime references
3. CODEOWNERS ACKs (tested separately)

Ledger #5: Three signals gate the Phase 22 §22.4 deletion.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestShimDeletionThreeSignals:
    """Tests for the three-signal pre-condition gate."""

    def test_three_signals_required_documented(self) -> None:
        """Verify that three signals are documented as blocking conditions."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        assert acks_file.exists(), f"Pre-conditions file not found: {acks_file}"
        
        content = acks_file.read_text(encoding="utf-8")
        
        # All three signals must be mentioned
        assert "Signal 1:" in content, "Signal 1 (CI DeprecationWarning) not documented"
        assert "Signal 2:" in content, "Signal 2 (Runtime logs) not documented"
        assert "Signal 3:" in content, "Signal 3 (CODEOWNERS acks) not documented"
        
        # Each signal must have a requirement stated
        assert "Zero" in content, "Zero-threshold requirement not stated"
        assert "14" in content or "14-day" in content, "14-day rolling window not mentioned"

    def test_ci_warnings_gate_documented(self) -> None:
        """Signal 1: CI DeprecationWarnings gate is documented."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Signal 1 must mention deprecation warnings and CI pipeline count
        signal1_section = content[content.find("Signal 1:"):content.find("Signal 2:")]
        assert "DeprecationWarning" in signal1_section or "deprecation" in signal1_section.lower()
        assert "50" in signal1_section, "Minimum 50 CI pipelines not mentioned"

    def test_runtime_logs_gate_documented(self) -> None:
        """Signal 2: Production runtime logs gate is documented."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Signal 2 must mention production and runtime logs
        signal2_section = content[content.find("Signal 2:"):content.find("Signal 3:")]
        assert "production" in signal2_section.lower() or "runtime" in signal2_section.lower()
        assert "shim.runtime.report" in content, "shim.runtime.report command not referenced"

    def test_codeowners_gate_documented(self) -> None:
        """Signal 3: CODEOWNERS ACK gate is documented."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Signal 3 must mention CODEOWNERS and ACK
        signal3_section = content[content.find("Signal 3:"):content.find("---", content.find("Signal 3:"))]
        assert "CODEOWNERS" in signal3_section or "codeowner" in signal3_section.lower()
        assert "ACK" in signal3_section or "ack" in signal3_section.lower()

    def test_15_day_burn_in_window_documented(self) -> None:
        """Verify 14-day continuous green requirement is documented."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Must mention 14-day rolling window (or similar)
        assert "14" in content and ("day" in content.lower() or "window" in content.lower())

    def test_signals_are_independent(self) -> None:
        """Verify that all three signals must be met (not OR logic)."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # The language should indicate all three must be true (AND logic)
        assert "all three" in content.lower() or "all" in content.lower() and "signals" in content.lower()
        assert "must" in content.lower()

    def test_pre_conditions_block_phase_22_deletion(self) -> None:
        """Verify that pre-conditions explicitly block Phase 22 deletion."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should clearly state deletion is blocked
        assert "blocked" in content.lower() or "cannot proceed" in content.lower()
        assert "Phase 22" in content or "§22.4" in content

    def test_signals_are_green_status_tracked(self) -> None:
        """Verify that each signal has a status column showing current state."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Status should be clearly visible
        assert "Status" in content or "status" in content
        # Status should show "pending" or similar until green
        assert "pending" in content.lower() or "⏳" in content

    def test_command_references_present(self) -> None:
        """Verify that make commands for checking signals are referenced."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should reference make commands for querying signal status
        assert "make" in content.lower()
        assert "shim.ci_warnings.report" in content or "ci_warnings" in content
        assert "shim.runtime.report" in content or "runtime.report" in content
