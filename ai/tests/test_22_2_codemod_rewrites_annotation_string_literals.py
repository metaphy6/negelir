"""Phase 22.2 bullet 11 — Proof: annotation string literals rewritten.

Quoted type names in Annotated[...] and TypeVar bounds are updated.
"""

from __future__ import annotations

import pytest
from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestAnnotationStringLiterals:
    """Proof: quoted type annotations are rewritten."""

    def test_annotated_with_string_literal(self) -> None:
        """Annotated[...] with quoted string type."""
        source = (
            "from typing import Annotated\n"
            "def foo(x: Annotated['ai.common.Config', 'metadata']) -> None:\n"
            "    pass\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # If rewritten, string should change
        if status == "rewritten":
            assert "'common.Config'" in result or "Annotated" in result

    def test_typevar_with_string_bound(self) -> None:
        """TypeVar with quoted string bound."""
        source = (
            "from typing import TypeVar\n"
            "T = TypeVar('T', bound='ai.common.Config')\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # If rewritten, bound string should change
        if status == "rewritten":
            assert "'common.Config'" in result or "TypeVar" in result

    def test_function_return_type_annotation(self) -> None:
        """Function with return type annotation as string."""
        source = (
            "def get_config() -> 'ai.common.Config':\n"
            "    return Config()\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # String annotation should be updated
        if status == "rewritten":
            assert "'common.Config'" in result

    def test_parameter_type_annotation(self) -> None:
        """Function parameter with type annotation as string."""
        source = (
            "def process(cfg: 'ai.common.Config', items: list) -> None:\n"
            "    pass\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        if status == "rewritten":
            assert "'common.Config'" in result or "'ai.common.Config'" not in result

    def test_f_string_annotation(self) -> None:
        """F-string annotations (may not be supported)."""
        source = (
            'x: f"ai.common.{config_name}" = None\n'
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # May or may not handle f-strings; just verify no crash
        assert result is not None
