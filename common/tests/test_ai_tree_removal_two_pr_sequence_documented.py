"""Phase 18.3 — Tests for two-PR sequence documentation.

Validates that the two-PR sequence for ai/ deletion is documented
and references all necessary components.

Ledger #4: Two-PR sequence gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestTwoPrSequenceDocumented:
    """Tests for two-PR sequence documentation."""

    def test_design_doc_exists(self) -> None:
        """The two-PR sequence design doc must exist."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        assert doc_file.exists(), f"Design doc not found: {doc_file}"

    def test_design_doc_explains_why_two_prs(self) -> None:
        """Design doc must explain why two PRs are needed."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should explain the problem with single PR
        assert "flag-day" in content.lower() or "single pr" in content.lower()
        # Should mention developer branches
        assert "branch" in content.lower()

    def test_pr_1_clearly_documented(self) -> None:
        """PR #1 (deletion + lint) must be clearly documented."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should have PR #1 section
        assert "PR #1" in content
        # Should mention deletion
        assert "delete" in content.lower()
        # Should mention lint
        assert "lint" in content.lower() or "resurrection" in content.lower()

    def test_pr_2_clearly_documented(self) -> None:
        """PR #2 (permanent gate) must be clearly documented."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should have PR #2 section
        assert "PR #2" in content
        # Should mention permanent gate
        assert "permanent" in content.lower() or "gate" in content.lower()

    def test_deprecation_window_documented(self) -> None:
        """The deprecation window must be documented."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should mention deprecation window
        assert "deprecation window" in content.lower() or "window" in content.lower()
        # Should mention 14 days
        assert "14" in content

    def test_emergency_rollback_process_documented(self) -> None:
        """The emergency rollback process must be documented."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should have emergency rollback section
        assert "emergency" in content.lower() or "rollback" in content.lower()
        # Should mention reverting
        assert "revert" in content.lower()

    def test_timeline_example_provided(self) -> None:
        """A timeline example should be provided."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should have timeline example
        assert "timeline" in content.lower() or "Day" in content or "day" in content.lower()

    def test_references_to_roadmap(self) -> None:
        """Design doc must reference ROADMAP sections."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should reference ROADMAP
        assert "ROADMAP" in content
        # Should reference the phase
        assert "18" in content or "22" in content

    def test_references_ledger(self) -> None:
        """Design doc must reference the ledger entry."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should reference ledger #4
        assert "ledger #4" in content.lower() or "#4" in content

    def test_codeowners_approval_mentioned(self) -> None:
        """Design doc must mention CODEOWNERS approval requirement."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should mention CODEOWNERS
        assert "codeowner" in content.lower()
        # Should mention approval
        assert "approv" in content.lower() or "ack" in content.lower()

    def test_test_references_mentioned(self) -> None:
        """Design doc should reference the test gates."""
        doc_file = (
            Path(__file__).resolve().parents[2]
            / "docs" / "design" / "phase18" / "two_pr_sequence_ai_deletion.md"
        )
        content = doc_file.read_text(encoding="utf-8")
        
        # Should mention test gates
        assert "test_ai_tree_gone" in content
        assert "test_ai_deletion_blocked" in content or "blocked" in content.lower()
