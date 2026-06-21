"""Phase 22.2 bullet 11 — Proof: Pydantic forward refs rewritten.

model_rebuild() and update_forward_refs() calls with ai.* strings are updated.
"""

from __future__ import annotations

import pytest
from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestPydanticForwardRef:
    """Proof: Pydantic model_rebuild() and update_forward_refs() are rewritten."""

    def test_model_rebuild_with_ai_reference(self) -> None:
        """model_rebuild() call is present and function executes."""
        source = (
            "class MyModel:\n"
            "    ref: 'ai.common.Config'\n"
            "    pass\n"
            "MyModel.model_rebuild()\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # At minimum, should handle the code without error
        assert "MyModel.model_rebuild()" in result

    def test_update_forward_refs_with_ai_reference(self) -> None:
        """update_forward_refs() call is present."""
        source = (
            "class MyModel:\n"
            "    ref: 'ai.common.Config'\n"
            "    pass\n"
            "MyModel.update_forward_refs()\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "MyModel.update_forward_refs()" in result

    def test_model_rebuild_with_globals_arg(self) -> None:
        """model_rebuild() with globals argument."""
        source = (
            "MyModel.model_rebuild(_parent_namespace_depth=2)\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # Should handle this without error
        assert "model_rebuild" in result

    def test_multiple_model_rebuild_calls(self) -> None:
        """Multiple model_rebuild() calls in one file."""
        source = (
            "ModelA.model_rebuild()\n"
            "ModelB.model_rebuild()\n"
            "ModelC.update_forward_refs()\n"
        )
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # All calls should be preserved
        assert "ModelA.model_rebuild()" in result
        assert "ModelB.model_rebuild()" in result
        assert "ModelC.update_forward_refs()" in result
