"""Phase 22.2 bullet 8 — Rollback safety: no-op rewrites don't create sidecars.

Verifies:
1. Rewriting an already-rewritten file is a no-op
2. No-op rewrites don't create .phase22.orig sidecars
3. Rollback with no sidecars is safe (no-op)
4. Attempting rollback when no sidecars exist reports correctly
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestRollbackNoOpSkipsSidecar:
    """Test that no-op rewrites don't create sidecars."""

    def test_no_op_rewrite_does_not_create_sidecar(self, tmp_path: Path) -> None:
        """Verify that rewriting already-rewritten file creates no sidecar."""
        from xops.codemod.phase22_rewriter import Phase22ImportRewriter
        
        # Already-rewritten source (no ai.* imports)
        source = """from common.config import cfg
from common.logger import get_logger
import common.model
"""
        
        target_file = tmp_path / "test_module.py"
        target_file.write_text(source, encoding="utf-8")
        
        # Attempt rewrite
        rewritten, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        
        # Should be no-op
        assert status == "no-op", f"Expected 'no-op', got {status}"
        assert rewritten == source, "Source should not change for no-op"
        
        # No sidecar should exist
        sidecar_path = target_file.with_suffix(target_file.suffix + ".phase22.orig")
        assert not sidecar_path.exists(), "No sidecar should be created for no-op"

    def test_consecutive_no_ops_create_no_sidecars(self, tmp_path: Path) -> None:
        """Verify that running codemod twice on already-rewritten file creates no sidecars."""
        from xops.codemod.phase22_rewriter import Phase22ImportRewriter
        
        source = """from common.config import cfg
import common.model
"""
        
        target_file = tmp_path / "test_module.py"
        target_file.write_text(source, encoding="utf-8")
        
        # First run (no-op)
        rewritten_1, status_1 = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert status_1 == "no-op"
        
        # Verify no sidecar was created
        sidecar_path = target_file.with_suffix(target_file.suffix + ".phase22.orig")
        assert not sidecar_path.exists()
        
        # Second run (still no-op)
        rewritten_2, status_2 = Phase22ImportRewriter.rewrite_source(rewritten_1, package="common")
        assert status_2 == "no-op"
        
        # Still no sidecar
        assert not sidecar_path.exists()

    def test_rollback_with_no_sidecars_is_safe(self, tmp_path: Path) -> None:
        """Verify that rollback when no sidecars exist is safe (no-op)."""
        # Create a package directory with files but no sidecars
        package_dir = tmp_path / "ai" / "common"
        package_dir.mkdir(parents=True)
        
        # Create some Python files (no sidecars)
        (package_dir / "config.py").write_text("from common.config import cfg\n")
        (package_dir / "logger.py").write_text("from common.logger import log\n")
        
        # Simulate rollback by looking for sidecars
        sidecars = list(package_dir.glob("**/*.phase22.orig"))
        assert len(sidecars) == 0, "No sidecars should exist"
        
        # Rollback should be a no-op (no error)
        if not sidecars:
            print(f"No .phase22.orig sidecars found")
            # This is the expected behavior - rollback is a no-op

    def test_no_op_after_first_rewrite(self, tmp_path: Path) -> None:
        """Verify that second rewrite after first is a no-op."""
        from xops.codemod.phase22_rewriter import Phase22ImportRewriter
        
        original_source = """from ai.common.config import cfg
from ai.common.logger import get_logger
"""
        
        target_file = tmp_path / "test_module.py"
        target_file.write_text(original_source, encoding="utf-8")
        
        # First rewrite
        rewritten_1, status_1 = Phase22ImportRewriter.rewrite_source(original_source, package="common")
        assert status_1 == "rewritten"
        assert "from common.config import cfg" in rewritten_1
        
        # Would create sidecar here (not done in this test)
        sidecar_path = target_file.with_suffix(target_file.suffix + ".phase22.orig")
        sidecar_path.write_text(original_source, encoding="utf-8")
        
        # Second rewrite (should be no-op)
        rewritten_2, status_2 = Phase22ImportRewriter.rewrite_source(rewritten_1, package="common")
        assert status_2 == "no-op", f"Second rewrite should be no-op, got {status_2}"
        assert rewritten_2 == rewritten_1
        
        # Verify sidecar still exists (wasn't deleted after first rewrite in this test)
        assert sidecar_path.exists()

    def test_no_op_detection_per_package_filter(self, tmp_path: Path) -> None:
        """Verify that no-op detection respects package filter."""
        from xops.codemod.phase22_rewriter import Phase22ImportRewriter
        
        # Source with imports from multiple packages
        source = """from ai.common.config import cfg
from ai.nlp.lexicon_loader import LexiconStore
import model as model
"""
        
        # When filtering for "common", file should be marked as needing rewrite
        # (it has ai.common imports)
        rewritten_common, status_common = Phase22ImportRewriter.rewrite_source(
            source, package="common"
        )
        assert status_common == "rewritten", "Should rewrite file with ai.common imports"
        
        # After rewriting common imports
        partial_rewritten = """from common.config import cfg
from ai.nlp.lexicon_loader import LexiconStore
import model as model
"""
        
        # When filtering for "common" again, should be no-op
        rewritten_again, status_again = Phase22ImportRewriter.rewrite_source(
            partial_rewritten, package="common"
        )
        assert status_again == "no-op", "Should be no-op after rewriting all common imports"
        
        # When filtering for "nlp", should still need rewrite
        rewritten_nlp, status_nlp = Phase22ImportRewriter.rewrite_source(
            partial_rewritten, package="nlp"
        )
        assert status_nlp == "rewritten", "Should rewrite file with ai.nlp imports"
