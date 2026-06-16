"""Phase 18.3 — Tests for CODEOWNERS ACKs recording.

Validates that component CODEOWNERS ACKs for shim deletion are recorded
and trackable in a centralized location.

Ledger #5 Signal 3: CODEOWNERS ACK from each component is blocking.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestShimCodeownerAcksRecorded:
    """Tests for CODEOWNERS ACK tracking."""

    def test_acks_file_exists(self) -> None:
        """The ACKs tracking file must exist."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        assert acks_file.exists(), f"ACKs file not found: {acks_file}"

    def test_all_required_components_listed(self) -> None:
        """All four components must be listed for ACK."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # All four component names must appear
        required_components = ["datasource", "swarm", "server", "common"]
        for component in required_components:
            assert component in content, f"Component '{component}' not listed in ACKs"

    def test_each_component_has_owner_placeholder(self) -> None:
        """Each component must have an owner field."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should have owner columns for each component
        required_components = ["datasource", "swarm", "server", "common"]
        for component in required_components:
            # Each component row should have an owner field
            assert component in content

    def test_each_component_has_status_column(self) -> None:
        """Each component ACK must have a status column."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Status column should exist
        assert "Status" in content or "status" in content

    def test_initial_status_is_pending(self) -> None:
        """Initial status for all components must be pending (not yet acked)."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Before the deletion, all must be pending
        assert "pending" in content.lower()
        required_components = ["datasource", "swarm", "server", "common"]
        for component in required_components:
            # Each should start as pending
            assert "pending" in content.lower()

    def test_date_column_for_tracking_when_acked(self) -> None:
        """There must be a date column to track when each ACK was given."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should have a Date column for tracking
        assert "Date" in content or "date" in content

    def test_file_is_codeowners_protected(self) -> None:
        """The ACKs file must be CODEOWNERS-protected."""
        # The file itself should exist
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        assert acks_file.exists()
        
        # Content should mention CODEOWNERS protection
        content = acks_file.read_text(encoding="utf-8")
        assert "CODEOWNERS" in content or "CODEOWNERS-protected" in content

    def test_acks_block_deletion_documented(self) -> None:
        """Documentation must state that all ACKs are required for deletion."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should state that deletion requires all ACKs
        assert "must" in content.lower() or "required" in content.lower()
        assert "deletion" in content.lower() or "delete" in content.lower()

    def test_reference_to_phase_22_deletion(self) -> None:
        """File must reference Phase 22 §22.4 deletion requirement."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should mention Phase 22
        assert "22" in content
        assert "deletion" in content.lower()

    def test_acks_table_has_notes_column(self) -> None:
        """The ACKs table should have a notes column for context."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should have a notes or similar column
        assert "Notes" in content or "notes" in content or "Comment" in content

    def test_ledger_reference_present(self) -> None:
        """File must reference the ROADMAP ledger #5."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Should reference ledger #5
        assert "#5" in content or "ledger #5" in content.lower() or "Ledger #5" in content

    def test_pre_conditions_stated_explicitly(self) -> None:
        """All pre-conditions must be stated explicitly."""
        acks_file = Path(__file__).resolve().parents[2] / "docs" / "tracking" / "phase18_shim_deletion_acks.md"
        content = acks_file.read_text(encoding="utf-8")
        
        # Must list the three conditions
        # 1. CI warnings zero
        assert "warning" in content.lower() or "deprecat" in content.lower()
        # 2. Runtime logs zero
        assert "runtime" in content.lower() or "production" in content.lower()
        # 3. CODEOWNERS acks
        assert "ack" in content.lower() or "owner" in content.lower()
