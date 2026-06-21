"""Phase 22.2 bullet 11 — Proof: codemod does NOT rewrite SQL/log strings.

Strings containing "ai." as part of non-import context are left unchanged.
Validates scope boundary: rewrites only import statements, not content.
"""

from __future__ import annotations

import pytest
from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestNonTargetPreservation:
    """Proof: non-import contexts with ai.* strings are unchanged."""

    def test_sql_string_with_ai_reference_unchanged(self) -> None:
        """SQL strings containing 'ai.' are not rewritten."""
        source = (
            "query = \"SELECT * FROM ai.common.users WHERE id = 1\""
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # SQL string should be unchanged
        assert 'ai.common.users' in result
        # Status should be no-op since no imports were found
        assert status == "no-op"

    def test_log_message_with_ai_reference_unchanged(self) -> None:
        """Log messages containing 'ai.' are not rewritten."""
        source = (
            'logger.info("Starting import from ai.common.config")'
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # Log message should be unchanged
        assert 'ai.common.config' in result
        # Status should be no-op
        assert status == "no-op"

    def test_comment_with_ai_reference_unchanged(self) -> None:
        """Code comments containing 'ai.' are not rewritten."""
        source = (
            "# This module was previously at ai.common.config\n"
            "from common.config import Config"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # Comment should be unchanged
        assert "# This module was previously at ai.common.config" in result
        # But import should be handled normally
        assert "from common.config import Config" in result

    def test_dict_key_with_ai_reference_unchanged(self) -> None:
        """Dictionary keys/values with 'ai.' strings are not rewritten."""
        source = (
            "mapping = {\"source\": \"ai.common.Config\", \"dest\": \"common.Config\"}"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # String values in dict should remain unchanged
        assert result == source
        assert status == "no-op"

    def test_mixed_imports_and_strings(self) -> None:
        """When both imports and non-import strings exist, only imports are rewritten."""
        source = (
            "from ai.common.config import Config\n"
            'error_msg = "Failed to load config from ai.common.config"\n'
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # Import should be rewritten
        assert "from common.config import Config" in result
        # String should be unchanged
        assert 'ai.common.config' in result
        assert status == "rewritten"

    @pytest.mark.parametrize(
        "non_target",
        [
            'print("ai.common.config")',
            'url = "https://example.com/ai/common/config"',
            "# TODO: refactor ai.common",
            "'ai.common.Config': 'common.Config',",
            "f\"Loading {ai.common.config}\" # should not change ai.common",
        ]
    )
    def test_various_non_target_strings(self, non_target: str) -> None:
        """Various non-import contexts are preserved."""
        # Add a valid import so status could be "rewritten"
        source = "from ai.common.config import Config\n" + non_target
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # The non-target portion should be unchanged
        assert non_target in result
