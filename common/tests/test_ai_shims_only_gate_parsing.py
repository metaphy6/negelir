"""Phase 18.3 — Tests for ai_shims_only gate parsing.

Validates that the shim-only lint correctly parses Python AST and
identifies shim-only modules.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Import the lint module
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "xops"))
from lint.ai_shims_only import validate_file


class TestShimGateParsing:
    """Tests for shim-only gate parsing logic."""

    def test_valid_shim_with_module_docstring(self) -> None:
        """Valid shim: module docstring + re-export imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                '"""Re-export module."""\n'
                "from datasource.scraper import extract_matches\n"
                "from common.schemas import Record\n"
                "\n"
                "__all__ = ['extract_matches', 'Record']\n",
                encoding="utf-8",
            )
            assert validate_file(shim_file) is True

    def test_valid_shim_without_docstring(self) -> None:
        """Valid shim without module docstring."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                "from swarm.predictor import predict\n"
                "from common.bus import publish\n"
                "\n"
                "__all__ = ['predict', 'publish']\n",
                encoding="utf-8",
            )
            assert validate_file(shim_file) is True

    def test_valid_shim_with_comments(self) -> None:
        """Valid shim with inline comments."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                '"""Re-export module."""\n'
                "# This is a re-export shim\n"
                "from datasource.emitter import emit\n"
                "# Publish interface\n"
                "from common.bus import Topic\n",
                encoding="utf-8",
            )
            assert validate_file(shim_file) is True

    def test_invalid_shim_with_class_definition(self) -> None:
        """Invalid shim: contains class definition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                '\nclass MyClass:\n'
                '    """Real implementation."""\n'
                '    pass\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_function_definition(self) -> None:
        """Invalid shim: contains function definition."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from swarm.predictor import predict\n'
                '\ndef my_function():\n'
                '    return 42\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_variable_assignment(self) -> None:
        """Invalid shim: contains variable assignment (not __all__)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from common.schemas import Record\n'
                '\nVERSION = "1.0.0"\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_conditional_logic(self) -> None:
        """Invalid shim: contains if statement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                '\nif True:\n'
                '    x = 1\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_disallowed_import(self) -> None:
        """Invalid shim: imports from disallowed module."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                'import numpy as np  # Real implementation dependency\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_relative_import(self) -> None:
        """Invalid shim: contains relative import."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from . import local_module\n'
                'from datasource.scraper import extract_matches\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_try_except(self) -> None:
        """Invalid shim: contains try/except block."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                '\ntry:\n'
                '    x = 1\n'
                'except Exception:\n'
                '    pass\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_invalid_shim_with_for_loop(self) -> None:
        """Invalid shim: contains for loop."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from common.schemas import Record\n'
                '\nfor i in range(10):\n'
                '    print(i)\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_valid_all_declaration_as_list(self) -> None:
        """Valid shim with __all__ as list literal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                '__all__ = ["extract_matches"]\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is True

    def test_valid_all_declaration_as_tuple(self) -> None:
        """Valid shim with __all__ as tuple literal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                '__all__ = ("extract_matches",)\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is True

    def test_invalid_all_not_literal(self) -> None:
        """Invalid shim: __all__ is not a literal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                '__all__ = dir()\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_syntax_error_in_file(self) -> None:
        """File with syntax error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text(
                'from datasource.scraper import extract_matches\n'
                'if True  # Missing colon\n',
                encoding="utf-8",
            )
            assert validate_file(shim_file) is False

    def test_empty_file_is_valid(self) -> None:
        """Empty file is a valid (trivial) shim."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text("", encoding="utf-8")
            assert validate_file(shim_file) is True

    def test_docstring_only_is_valid(self) -> None:
        """File with only a docstring is valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shim_file = Path(tmpdir) / "test_shim.py"
            shim_file.write_text('"""Module docstring only."""\n', encoding="utf-8")
            assert validate_file(shim_file) is True
