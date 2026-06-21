"""Phase 22.2 bullet 11 — Proof: codemod scope rejects non-.py files.

The codemod must enforce scope boundaries and validate that files
are .py files before processing. Non-.py files are rejected at the
file-validation layer via FileFilterValidator.validate_file().
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from xops.codemod.phase22_rewriter import FileFilterValidator, FileScopeError


class TestRejectsNonPyExtensions:
    """Proof: codemod enforces file extension boundary."""

    def test_validates_py_file_accepted(self) -> None:
        """The codemod must accept .py files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir) / "module.py"
            py_file.write_text("from ai.common.config import Config\n")
            
            try:
                FileFilterValidator.validate_file(py_file)
                assert True, ".py file should pass validation"
            except FileScopeError:
                pytest.fail(".py file should not be rejected")

    def test_validates_lock_file_rejected(self) -> None:
        """The codemod must reject .lock files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / "requirements.lock"
            lock_file.write_text("# some lock content")
            
            with pytest.raises(FileScopeError, match=r"\.lock"):
                FileFilterValidator.validate_file(lock_file)

    def test_validates_json_file_rejected(self) -> None:
        """The codemod must reject .json files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "betting_markets.json"
            json_file.write_text('{"market": "1x2"}')
            
            with pytest.raises(FileScopeError, match="JSON"):
                FileFilterValidator.validate_file(json_file)

    def test_validates_yaml_file_rejected(self) -> None:
        """The codemod must reject .yaml config files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_file = Path(tmpdir) / "league_catalog.yaml"
            yaml_file.write_text("leagues:\n  - name: Super Lig\n")
            
            with pytest.raises(FileScopeError, match="YAML"):
                FileFilterValidator.validate_file(yaml_file)

    def test_validates_go_file_rejected(self) -> None:
        """The codemod must reject .go source files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            go_file = Path(tmpdir) / "config.go"
            go_file.write_text('package config\n')
            
            with pytest.raises(FileScopeError, match=r"\.go"):
                FileFilterValidator.validate_file(go_file)

    def test_validates_pyc_file_rejected(self) -> None:
        """The codemod must reject .pyc compiled files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyc_file = Path(tmpdir) / "module.pyc"
            pyc_file.write_bytes(b"\x00\x00\x00\x00")
            
            with pytest.raises(FileScopeError, match=r"\.pyc"):
                FileFilterValidator.validate_file(pyc_file)

    def test_validates_sbom_spdx_file_rejected(self) -> None:
        """The codemod must reject .sbom.spdx.json files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sbom_file = Path(tmpdir) / "requirements.sbom.spdx.json"
            sbom_file.write_text('{"format": "SPDXv2.2"}')
            
            with pytest.raises(FileScopeError, match="SBOM"):
                FileFilterValidator.validate_file(sbom_file)
