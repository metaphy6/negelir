"""Phase 22.1 — Proof test: Rollback runbook committed and covers all steps."""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.mark.phase22
class TestRollbackRunbook:
    """Verify rollback runbook exists and covers all 12 steps."""

    def test_22_1_rollback_runbook_file_exists(self) -> None:
        """Test that rollback runbook file exists."""
        repo_root = Path(__file__).resolve().parents[2]
        runbook_path = repo_root / "docs" / "runbooks" / "phase22_rollback.md"
        assert runbook_path.exists(), f"Rollback runbook not found: {runbook_path}"

    def test_22_1_rollback_runbook_covers_all_steps(self) -> None:
        """Test that runbook documents all 12 rollback steps."""
        repo_root = Path(__file__).resolve().parents[2]
        runbook_path = repo_root / "docs" / "runbooks" / "phase22_rollback.md"
        
        with open(runbook_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for each step
        expected_steps = [
            "Step 1",  # Pre-flight
            "Step 2",  # Codemod
            "Step 3a", # common/ merge
            "Step 3b", # ai/tests/ merge
            "Step 3c", # ai/swarm/ merge
            "Step 3d", # ai/docs/ merge
            "Step 4",  # Package moves
            "Step 5",  # Go references
            "Step 6",  # Config migration
            "Step 7",  # Deletion
            "Step 8",  # Snapshot finalization
            "Step 9",  # Metric names (moved to 22.9 in doc structure)
        ]
        
        for step in expected_steps:
            assert step in content, f"Rollback runbook missing {step}"

    def test_22_1_rollback_runbook_has_manual_procedure(self) -> None:
        """Test that runbook includes manual rollback procedures."""
        repo_root = Path(__file__).resolve().parents[2]
        runbook_path = repo_root / "docs" / "runbooks" / "phase22_rollback.md"
        
        with open(runbook_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for manual procedure section
        assert "Manual rollback" in content
        assert "git revert" in content
        assert "git checkout" in content

    def test_22_1_rollback_runbook_has_verification_section(self) -> None:
        """Test that runbook includes verification steps."""
        repo_root = Path(__file__).resolve().parents[2]
        runbook_path = repo_root / "docs" / "runbooks" / "phase22_rollback.md"
        
        with open(runbook_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for verification sections
        assert "Verification:" in content
        assert "make isolation.check --full" in content

    def test_22_1_rollback_runbook_has_emergency_escalation(self) -> None:
        """Test that runbook documents escalation procedure."""
        repo_root = Path(__file__).resolve().parents[2]
        runbook_path = repo_root / "docs" / "runbooks" / "phase22_rollback.md"
        
        with open(runbook_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        assert "Emergency Escalation Procedure" in content or "Escalation" in content
        assert "make track.add" in content

    def test_22_1_rollback_runbook_references_architecture(self) -> None:
        """Test that runbook documents the 14-step architecture."""
        repo_root = Path(__file__).resolve().parents[2]
        runbook_path = repo_root / "docs" / "runbooks" / "phase22_rollback.md"
        
        with open(runbook_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for architecture table
        assert "Architecture of the" in content or "Migration Steps" in content
        assert "package" in content.lower()
