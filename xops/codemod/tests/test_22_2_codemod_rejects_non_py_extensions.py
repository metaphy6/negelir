"""Phase 22.2 bullet 2 — Codemod scope boundary tests.

Tests that the libcst codemod engine rejects non-*.py files,
including .lock, .sbom.spdx.json, .yaml, .go, .json, and .pyc files.

Implements binding requirement: "A test asserts the codemod's file filter
rejects every non-.py extension."
"""

from __future__ import annotations

import pytest
from pathlib import Path

from xops.codemod.phase22_rewriter import FileFilterValidator, FileScopeError


class TestCodemodScopeBoundary:
    """Test that FileFilterValidator rejects non-*.py extensions."""
    
    def test_accepts_plain_python_files(self) -> None:
        """Valid: *.py files are accepted."""
        validator = FileFilterValidator()
        
        # Should not raise
        validator.validate_file(Path("ai/common/config.py"))
        validator.validate_file(Path("tests/test_example.py"))
        validator.validate_file(Path("xops/makefile/phase22.py"))
    
    def test_rejects_requirements_lock(self) -> None:
        """Invalid: requirements.lock is rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/requirements.lock"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert "requirements.lock" in error_msg
        assert "Phase 22.2 bullet 2" in error_msg
    
    def test_rejects_sbom_spdx_json(self) -> None:
        """Invalid: *.sbom.spdx.json files are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/swarm.sbom.spdx.json"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert "sbom" in error_msg.lower()
        assert "§22.4" in error_msg  # References lock/SBOM regen phase
    
    def test_rejects_pyc_files(self) -> None:
        """Invalid: *.pyc bytecode files are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/common/__pycache__/config.pyc"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert ".pyc" in error_msg
    
    def test_rejects_pyo_files(self) -> None:
        """Invalid: *.pyo optimized bytecode files are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/__pycache__/module.pyo"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
    
    def test_rejects_yaml_config_files(self) -> None:
        """Invalid: *.yaml config files are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("datasource/config.yaml"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert "yaml" in error_msg.lower()
    
    def test_rejects_yml_config_files(self) -> None:
        """Invalid: *.yml config files are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("datasource/pipeline.yml"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
    
    def test_rejects_go_source_files(self) -> None:
        """Invalid: *.go source files are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("server/api/handlers.go"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert ".go" in error_msg
    
    def test_rejects_data_json_files(self) -> None:
        """Invalid: *.json data files outside tests/ are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("data/super_lig_real.json"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert "json" in error_msg.lower()
    
    def test_rejects_league_catalog_json(self) -> None:
        """Invalid: league_catalog.json is rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("league_catalog.json"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert "§22.3a" in error_msg  # References data-contract moves
    
    def test_accepts_json_in_test_fixtures(self) -> None:
        """Valid: *.json test fixtures in tests/ directories are accepted."""
        # Should not raise
        FileFilterValidator.validate_file(Path("ai/tests/fixtures/league_catalog.json"))
        FileFilterValidator.validate_file(Path("tests/fixtures/data.json"))
    
    def test_accepts_yaml_in_test_fixtures(self) -> None:
        """Valid: *.yaml test fixtures in tests/ directories are accepted."""
        # Should not raise
        FileFilterValidator.validate_file(Path("ai/tests/fixtures/config.yaml"))
        FileFilterValidator.validate_file(Path("tests/fixtures/thresholds.yml"))
    
    def test_rejects_json_outside_tests(self) -> None:
        """Invalid: unknown *.json files outside tests/ are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("config/unknown_data.json"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
        assert "json" in error_msg.lower()
    
    def test_rejects_so_files(self) -> None:
        """Invalid: *.so (Unix shared objects) are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/lib/native.so"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
    
    def test_rejects_pyd_files(self) -> None:
        """Invalid: *.pyd (Windows extensions) are rejected."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/lib/native.pyd"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()


class TestValidateFileList:
    """Test batch validation of multiple files."""
    
    def test_validate_homogeneous_py_list_succeeds(self) -> None:
        """Valid: a list of only *.py files passes."""
        files = [
            Path("ai/common/config.py"),
            Path("ai/scraper/extractor.py"),
            Path("tests/test_example.py"),
        ]
        # Should not raise
        FileFilterValidator.validate_file_list(files)
    
    def test_validate_mixed_list_raises_on_first_violation(self) -> None:
        """Invalid: a list with one non-*.py file raises on first match."""
        files = [
            Path("ai/common/config.py"),
            Path("requirements.lock"),  # Violation
            Path("ai/scraper/extractor.py"),
        ]
        
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file_list(files)
        
        error_msg = str(exc_info.value)
        assert "requirements.lock" in error_msg
    
    def test_filter_violations_separates_valid_from_invalid(self) -> None:
        """Valid and invalid files are separated by filter_scope_violations."""
        files = [
            Path("ai/common/config.py"),
            Path("ai/requirements.lock"),
            Path("ai/scraper/extractor.py"),
            Path("ai/datasource/config.yaml"),
            Path("tests/test_phase22.py"),
            Path("server/api/handlers.go"),
        ]
        
        valid, violations = FileFilterValidator.filter_scope_violations(files)
        
        # Only *.py files should be valid
        assert len(valid) == 3
        assert all(str(f).endswith('.py') for f in valid)
        
        # Non-*.py files should be violations
        assert len(violations) == 3
        
        # Check that violations have error messages
        for file_path, error_msg in violations:
            assert isinstance(file_path, Path)
            assert isinstance(error_msg, str)
            assert "cannot touch" in error_msg.lower()
            assert "phase 22.2 bullet 2" in error_msg.lower()
    
    def test_filter_violations_with_empty_list(self) -> None:
        """Empty file list returns empty results."""
        valid, violations = FileFilterValidator.filter_scope_violations([])
        
        assert valid == []
        assert violations == []
    
    def test_filter_violations_with_all_valid_files(self) -> None:
        """All-valid file list has no violations."""
        files = [
            Path("ai/common/config.py"),
            Path("ai/scraper/extractor.py"),
            Path("tests/test_phase22.py"),
        ]
        
        valid, violations = FileFilterValidator.filter_scope_violations(files)
        
        assert len(valid) == 3
        assert violations == []


class TestErrorMessages:
    """Test that error messages are clear and actionable."""
    
    def test_error_messages_reference_phase_and_bullet(self) -> None:
        """All scope-boundary errors reference Phase 22.2 bullet 2."""
        test_cases = [
            Path("requirements.lock"),
            Path("config.yaml"),
            Path("server/api.go"),
            Path("data/league.json"),
        ]
        
        for file_path in test_cases:
            with pytest.raises(FileScopeError) as exc_info:
                FileFilterValidator.validate_file(file_path)
            
            error_msg = str(exc_info.value)
            assert "phase 22.2 bullet 2" in error_msg.lower(), f"Missing phase ref in: {error_msg}"
    
    def test_error_messages_reference_owning_phase(self) -> None:
        """Error messages hint at the owning phase (§22.3a, §22.4, §22.5)."""
        # SBOM files should reference §22.4
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("ai/swarm.sbom.spdx.json"))
        assert "§22.4" in str(exc_info.value)
        
        # Data JSON should reference §22.3a
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("league_catalog.json"))
        assert "§22.3a" in str(exc_info.value)


class TestBoundaryConditions:
    """Test edge cases and boundary conditions."""
    
    def test_conftest_allowed_as_valid_python_file(self) -> None:
        """conftest.py is allowed (it's a valid Python file with potential imports)."""
        # conftest.py is a valid Python file that may have imports to rewrite
        # It is handled as part of the general test-file reconciliation in Phase 22.3b
        FileFilterValidator.validate_file(Path("conftest.py"))
        FileFilterValidator.validate_file(Path("ai/tests/conftest.py"))
        FileFilterValidator.validate_file(Path("ai/swarm/agents/maint/tests/conftest.py"))
    
    def test_setup_py_rejected(self) -> None:
        """setup.py is rejected (special packaging file)."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("setup.py"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
    
    def test_pyproject_toml_rejected(self) -> None:
        """pyproject.toml is rejected (special packaging file)."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("pyproject.toml"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
    
    def test_hidden_dotfiles_rejected(self) -> None:
        """.env and .gitignore are rejected."""
        with pytest.raises(FileScopeError):
            FileFilterValidator.validate_file(Path(".env"))
        
        with pytest.raises(FileScopeError):
            FileFilterValidator.validate_file(Path(".gitignore"))
    
    def test_poetry_lock_rejected(self) -> None:
        """poetry.lock is rejected (like requirements.lock)."""
        with pytest.raises(FileScopeError) as exc_info:
            FileFilterValidator.validate_file(Path("poetry.lock"))
        
        error_msg = str(exc_info.value)
        assert "cannot touch" in error_msg.lower()
