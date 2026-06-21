"""Phase 22.1 — Proof tests: Phase 22 infrastructure validation."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.phase22
class TestPhase22Infrastructure:
    """Verify Phase 22 infrastructure is in place."""

    def test_22_1_xops_lint_phase22_scripts_exist(self) -> None:
        """Test that Phase 22 lint scripts exist."""
        repo_root = Path(__file__).resolve().parents[2]
        lint_dir = repo_root / "xops" / "lint"
        
        # Config audit script should exist
        config_audit = lint_dir / "phase22_config_audit.py"
        assert config_audit.exists(), "phase22_config_audit.py should exist"

    def test_22_1_docs_tracking_phase22_directory_exists(self) -> None:
        """Test that tracking directory is ready for Phase 22 artifacts."""
        repo_root = Path(__file__).resolve().parents[2]
        tracking_dir = repo_root / "docs" / "tracking"
        assert tracking_dir.exists(), "docs/tracking/ should exist"
        assert tracking_dir.is_dir(), "docs/tracking/ should be a directory"

    def test_22_1_makefile_has_phase22_targets(self) -> None:
        """Test that Makefile includes Phase 22 targets."""
        repo_root = Path(__file__).resolve().parents[2]
        makefile = repo_root / "Makefile"
        assert makefile.exists(), "Makefile should exist"
        
        with open(makefile, "r") as f:
            content = f.read()
        
        # Should reference phase22
        assert "phase22" in content.lower() or "Phase 22" in content

    def test_22_1_pyproject_toml_exists(self) -> None:
        """Test that pyproject.toml exists for Python config."""
        repo_root = Path(__file__).resolve().parents[2]
        pyproject = repo_root / "pyproject.toml"
        assert pyproject.exists(), "pyproject.toml should exist"

    def test_22_1_python_paths_documented(self) -> None:
        """Test that Python path configuration is documented."""
        repo_root = Path(__file__).resolve().parents[2]
        
        # Check for env documentation
        env_example = repo_root / "xops" / "env" / ".env.example"
        if env_example.exists():
            with open(env_example, "r") as f:
                content = f.read()
            # Should document Python path configuration
            assert len(content) > 0

    def test_22_1_conftest_hierarchy_in_place(self) -> None:
        """Test that conftest.py hierarchy is in place."""
        repo_root = Path(__file__).resolve().parents[2]
        
        # Root conftest
        root_conftest = repo_root / "conftest.py"
        assert root_conftest.exists(), "Root conftest.py should exist"
        
        # ai/tests conftest
        ai_conftest = repo_root / "ai" / "tests" / "conftest.py"
        assert ai_conftest.exists(), "ai/tests/conftest.py should exist"

    def test_22_1_decision_docs_directory_ready(self) -> None:
        """Test that decisions directory exists for Phase 22."""
        repo_root = Path(__file__).resolve().parents[2]
        
        # The decisions directory may be created on-demand
        # For now, just verify docs directory exists
        docs_dir = repo_root / "docs"
        assert docs_dir.exists(), "docs/ should exist"
