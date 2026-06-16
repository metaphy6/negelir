"""Phase 18.3 & §22.4 — Test that ai/ tree is absent.

This test validates that the ai/ directory has been deleted as part of
Phase 22 §22.4. The test will FAIL until Phase 22 executes the deletion.

Status: Expected to FAIL during Phase 18 (ai/ still contains code)
         Expected to PASS after Phase 22 §22.4 (ai/ deleted)
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestAiTreeGone:
    """Test that the ai/ directory is properly deleted."""

    def test_ai_directory_does_not_exist(self) -> None:
        """The ai/ directory must not exist after Phase 22 §22.4."""
        repo_root = Path(__file__).resolve().parents[2]
        ai_root = repo_root / "ai"
        
        # This test MUST FAIL until Phase 22 deletes ai/
        assert not ai_root.exists(), (
            f"ai/ directory still exists at {ai_root}. "
            "Phase 22 §22.4 deletion has not been executed. "
            "The shim-only gate (make isolation.shims-only) must be green "
            "and the three pre-condition signals must be verified before deletion."
        )

    def test_ai_parent_structure_intact(self) -> None:
        """Other directories at repo root must still exist."""
        repo_root = Path(__file__).resolve().parents[2]
        
        # These directories should exist (after ai/ deletion)
        assert (repo_root / "common").exists(), "common/ missing"
        assert (repo_root / "server").exists(), "server/ missing"
        assert (repo_root / "xops").exists(), "xops/ missing"
        assert (repo_root / "docs").exists(), "docs/ missing"

    def test_ai_deletion_is_permanent(self) -> None:
        """After deletion, ai/ must never be resurrected."""
        repo_root = Path(__file__).resolve().parents[2]
        ai_root = repo_root / "ai"
        
        # Check that ai/ is gone
        assert not ai_root.exists(), (
            "ai/ has been resurrected after deletion. "
            "This violates the Phase 22 §22.4 deletion contract. "
            "Emergency rollback requires [RELAX_AI_TREE_RESURRECTION] marker."
        )
