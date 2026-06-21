"""Phase 19 §19.1 — ai/ layout freeze enforcement.

Tests that the lint rule `xops/lint/ai_layout_freeze.py` blocks new top-level
modules in ai/, ensuring orderly migration to Phase 22.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "xops" / "lint"))

from ai_layout_freeze import check_ai_layout_freeze, ALLOWED_AI_MODULES


class TestAiLayoutFreeze:
    """Test ai/ layout freeze enforcement."""
    
    def test_allowed_ai_modules_pass_checks(self, tmp_path: Path) -> None:
        """Verify that pre-existing AI modules are allowed."""
        # Create the ai/ directory with allowed modules
        ai_root = tmp_path / "ai"
        ai_root.mkdir()
        
        # Create all allowed modules
        for module in ["common", "scraper", "nlp", "swarm", "pipeline"]:
            (ai_root / module).mkdir()
            (ai_root / module / "__init__.py").touch()
        
        # Check should pass
        errors = check_ai_layout_freeze(tmp_path)
        assert errors == []
    
    def test_new_module_is_blocked(self, tmp_path: Path) -> None:
        """Verify that new modules are blocked by the freeze."""
        # Create the ai/ directory
        ai_root = tmp_path / "ai"
        ai_root.mkdir()
        
        # Create a pre-existing allowed module
        (ai_root / "common").mkdir()
        (ai_root / "common" / "__init__.py").touch()
        
        # Try to add a new module (not in ALLOWED_AI_MODULES)
        (ai_root / "new_module").mkdir()
        (ai_root / "new_module" / "__init__.py").touch()
        
        # Check should fail
        errors = check_ai_layout_freeze(tmp_path)
        assert len(errors) == 1
        assert "New ai/ module not allowed" in errors[0]
        assert "ai/new_module/" in errors[0]
    
    def test_multiple_new_modules_reported(self, tmp_path: Path) -> None:
        """Verify that all violations are reported."""
        ai_root = tmp_path / "ai"
        ai_root.mkdir()
        
        # Create several new modules
        for new_mod in ["new_alpha", "new_beta", "new_gamma"]:
            (ai_root / new_mod).mkdir()
            (ai_root / new_mod / "__init__.py").touch()
        
        # Check should report all violations
        errors = check_ai_layout_freeze(tmp_path)
        assert len(errors) == 3
    
    def test_special_files_ignored(self, tmp_path: Path) -> None:
        """Verify that special files (not modules) are ignored."""
        ai_root = tmp_path / "ai"
        ai_root.mkdir()
        
        # Create allowed modules
        (ai_root / "common").mkdir()
        
        # Create special files (these should be ignored)
        (ai_root / "main.py").touch()
        (ai_root / "scheduler.py").touch()
        (ai_root / "requirements.txt").touch()
        (ai_root / ".gitignore").touch()  # Hidden file, should be ignored
        (ai_root / "__pycache__").mkdir()  # Special dir, should be ignored
        
        # Check should pass
        errors = check_ai_layout_freeze(tmp_path)
        assert errors == []
    
    def test_docs_and_tests_allowed(self, tmp_path: Path) -> None:
        """Verify that docs/ and tests/ directories are allowed."""
        ai_root = tmp_path / "ai"
        ai_root.mkdir()
        
        # Create allowed modules and support directories
        (ai_root / "common").mkdir()
        (ai_root / "docs").mkdir()
        (ai_root / "tests").mkdir()
        (ai_root / "datasource").mkdir()
        
        # Check should pass
        errors = check_ai_layout_freeze(tmp_path)
        assert errors == []
    
    def test_partial_phase_22_migration_blocked_until_ready(self, tmp_path: Path) -> None:
        """
        Document that partial migrations are blocked.
        
        If someone tries to move ai/scraper to datasource/scraper before
        Phase 22 is ready, and creates a new "scraper" module, the freeze
        will catch it.
        """
        ai_root = tmp_path / "ai"
        ai_root.mkdir()
        
        # Start of an unauthorized migration attempt:
        # Someone created a new scraper module (maybe for a different purpose)
        (ai_root / "scraper").mkdir()  # This is allowed (pre-existing)
        
        # But if they try to add something that looks like a new path:
        (ai_root / "newdata").mkdir()  # This should be blocked
        
        errors = check_ai_layout_freeze(tmp_path)
        assert len(errors) == 1
        assert "ai/newdata/" in errors[0]
    
    def test_freeze_is_mandatory(self) -> None:
        """Document that the freeze is mandatory (no exceptions)."""
        # The freeze is a hard gate per the ROADMAP
        # It is checked in every CI run after this bullet lands
        # There is no exception pathway or approval process
        
        # Verify the ALLOWED_AI_MODULES is the canonical list
        expected = {
            "common", "scraper", "nlp", "swarm", "pipeline",
            "backtest", "orchestrator", "model", "proofreader",
            "qid", "reports", "tqu", "trc",
            "scheduler.py", "main.py", "data_showcase.py",
            "requirements.txt", "requirements-dev.txt",
            "Dockerfile", "__init__.py", "docs", "tests", "datasource"
        }
        
        assert ALLOWED_AI_MODULES == expected, \
            f"ALLOWED_AI_MODULES mismatch. Expected {expected}, got {ALLOWED_AI_MODULES}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
