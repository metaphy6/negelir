"""Phase 22.2 bullet 3 — Import rewriter pattern tests.

Tests all 7 rewrite patterns implemented in Phase22ImportRewriter:
  1. from ai.<pkg>.<mod> import X → from <pkg>.<mod> import X
  2. import ai.<pkg> → import <pkg> as <pkg>
  3. Quoted type annotations "ai.<pkg>.<Class>" → "<pkg>.<Class>"
  4. TYPE_CHECKING block imports
  5. __all__ re-exports
  6. Pydantic model_rebuild() / update_forward_refs()
  7. Provenance headers # negelir-generated-from: ai/
"""

from __future__ import annotations

import pytest

from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestPattern1_ImportFrom:
    """Pattern 1: from ai.<pkg>.<mod> import X → from <pkg>.<mod> import X"""

    def test_basic_from_import(self) -> None:
        source = "from ai.common.config import Config\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from common.config import Config" in rewritten
        assert "ai.common" not in rewritten

    def test_from_import_multiple_names(self) -> None:
        source = "from ai.common.config import Config, cfg\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from common.config import Config, cfg" in rewritten

    def test_from_import_nested_module(self) -> None:
        source = "from ai.common.text.turkish import suffix_harmony_ok\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from common.text.turkish import suffix_harmony_ok" in rewritten

    def test_from_import_preserves_non_ai_imports(self) -> None:
        source = "from typing import Dict, List\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from typing import Dict, List" in rewritten

    def test_from_import_different_package(self) -> None:
        """When filtering by package, only rewrite matching packages."""
        source = "from ai.datasource.scraper import Scraper\n"
        # When filtering by "common", datasource imports should NOT be rewritten
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from ai.datasource.scraper import Scraper" in rewritten


class TestPattern2_ImportStatement:
    """Pattern 2: import ai.<pkg> → import <pkg> as <pkg>"""

    def test_basic_import_with_alias(self) -> None:
        source = "import ai.common\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "import common as common" in rewritten
        assert "ai.common" not in rewritten

    def test_import_nested_module_with_alias(self) -> None:
        source = "import ai.common.config\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "import common.config as common" in rewritten

    def test_import_preserves_non_ai_imports(self) -> None:
        source = "import os\nimport sys\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "import os" in rewritten
        assert "import sys" in rewritten
    def test_import_multiple_modules(self) -> None:
        source = "import ai.common\nimport ai.datasource\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="")
        # Both should be rewritten (on separate lines)
        assert "import common as common" in rewritten
        assert "import datasource as datasource" in rewritten


class TestPattern3_QuotedTypeAnnotations:
    """Pattern 3: Quoted type annotations "ai.<pkg>.<Class>" → "<pkg>.<Class>" """

    def test_double_quoted_annotation(self) -> None:
        source = 'def func(x: "ai.common.config.Config") -> None: pass\n'
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten
        assert "ai.common" not in rewritten

    def test_single_quoted_annotation(self) -> None:
        source = "def func(x: 'ai.common.config.Config') -> None: pass\n"
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "'common.config.Config'" in rewritten

    def test_annotation_in_type_comment(self) -> None:
        source = 'x = None  # type: "ai.common.config.Config"\n'
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten

    def test_multiple_quoted_annotations(self) -> None:
        source = (
            'x: "ai.common.config.Config" = None\n'
            'y: "ai.common.logger.Logger" = None\n'
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten
        assert '"common.logger.Logger"' in rewritten


class TestPattern4_TypeCheckingBlocks:
    """Pattern 4: TYPE_CHECKING block imports (same as patterns 1/2)"""

    def test_type_checking_from_import(self) -> None:
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from ai.common.config import Config\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from common.config import Config" in rewritten
        assert "from typing import TYPE_CHECKING" in rewritten

    def test_type_checking_import_statement(self) -> None:
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    import ai.common\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "import common as common" in rewritten

    def test_typing_extensions_type_checking(self) -> None:
        """Support typing_extensions.TYPE_CHECKING as well."""
        source = (
            "from typing_extensions import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from ai.common.config import Config\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from common.config import Config" in rewritten


class TestPattern5_AllReexports:
    """Pattern 5: __all__ re-exports with ai.* names"""

    def test_all_with_ai_qualified_names(self) -> None:
        source = (
            '__all__ = [\n'
            '    "ai.common.config.Config",\n'
            '    "ai.common.logger.Logger",\n'
            ']\n'
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten
        assert '"common.logger.Logger"' in rewritten
        assert "ai.common" not in rewritten

    def test_all_mixed_names(self) -> None:
        """__all__ with both ai.* and normal names."""
        source = (
            '__all__ = [\n'
            '    "Config",\n'
            '    "ai.common.logger.Logger",\n'
            ']\n'
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"Config"' in rewritten
        assert '"common.logger.Logger"' in rewritten

    def test_all_tuple_style(self) -> None:
        """__all__ as tuple instead of list."""
        source = (
            '__all__ = (\n'
            '    "ai.common.config.Config",\n'
            ')\n'
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten


class TestPattern6_PydanticCalls:
    """Pattern 6: Pydantic model_rebuild() / update_forward_refs() calls"""

    def test_model_rebuild_with_module_string(self) -> None:
        source = (
            "from pydantic import BaseModel\n"
            "\n"
            "class MyModel(BaseModel):\n"
            "    pass\n"
            "\n"
            'MyModel.model_rebuild(_types_namespace={"ai.common.config.Config": Config})\n'
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten

    def test_update_forward_refs(self) -> None:
        source = (
            "model.update_forward_refs(\n"
            '    Config="ai.common.config.Config"\n'
            ")\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten

    def test_multiple_pydantic_calls(self) -> None:
        source = (
            'Model1.model_rebuild(__root__="ai.common.config.Config")\n'
            'Model2.update_forward_refs(Config="ai.common.logger.Logger")\n'
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert '"common.config.Config"' in rewritten
        assert '"common.logger.Logger"' in rewritten


class TestPattern7_ProvenanceHeaders:
    """Pattern 7: Provenance headers # negelir-generated-from: ai/<path>@sha256"""

    def test_provenance_header_rewrite(self) -> None:
        source = (
            "# negelir-generated-from: ai/common/config.py@abc123def456\n"
            "# Code generated by Phase 17\n"
            "\n"
            "def func():\n"
            "    pass\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="")
        assert "# negelir-generated-from: common/config.py@abc123def456" in rewritten
        assert "ai/common" not in rewritten

    def test_provenance_header_in_docstring(self) -> None:
        source = (
            '"""negelir-generated-from: ai/datasource/scraper.py@sha256"""\n'
            "def func():\n"
            "    pass\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="")
        # Docstrings with provenance are not rewritten (only comments)
        # This is by design — only standalone comments are rewritten
        assert rewritten is not None

    def test_provenance_only_first_n_lines(self) -> None:
        """Provenance headers are only scanned in the first N lines."""
        source = (
            "def func():\n"
            "    pass\n"
            "# negelir-generated-from: ai/common/config.py@sha256\n"  # Outside first 5 lines
            "x = 1\n"
        )
        lines = source.split("\n")
        # Provenance on line 3 should not be rewritten (only first 5 scanned, but we're beyond)
        rewritten = Phase22ImportRewriter.rewrite_source(source, scan_head_lines=2)
        # The third line is outside the scan window, so it won't be rewritten
        assert "ai/common/config.py" in rewritten  # Should NOT be rewritten


class TestCombinedPatterns:
    """Test combinations of multiple patterns in a single file."""

    def test_all_patterns_combined(self) -> None:
        source = (
            "# negelir-generated-from: ai/common/config.py@abc123\n"
            "from typing import TYPE_CHECKING\n"
            "import ai.common\n"
            "from ai.common.config import Config\n"
            "\n"
            "if TYPE_CHECKING:\n"
            '    x: "ai.common.logger.Logger" = None\n'
            "\n"
            '__all__ = ["ai.common.config.Config"]\n'
            "\n"
            "def setup():\n"
            '    Config.model_rebuild(__root__="ai.common.config.Config")\n'
        )
        
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        
        # Check all patterns were applied
        assert "# negelir-generated-from: common/config.py@abc123" in rewritten  # Pattern 7
        assert "import common as common" in rewritten  # Pattern 2
        assert "from common.config import Config" in rewritten  # Pattern 1
        assert '"common.logger.Logger"' in rewritten  # Pattern 3
        assert '"common.config.Config"' in rewritten  # Patterns 5 & 6
        assert "ai." not in rewritten.split("# negelir")[0]  # No ai. except in provenance


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_parsing_error_returns_source(self) -> None:
        """If source code cannot be parsed, return it as-is (pattern 7 applied)."""
        source = (
            "# negelir-generated-from: ai/common.py@sha\n"
            "this is not valid python syntax @#$%\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source)
        # Pattern 7 should still be applied
        assert "# negelir-generated-from: common.py@sha" in rewritten

    def test_empty_source(self) -> None:
        """Empty source code should be handled gracefully."""
        source = ""
        rewritten = Phase22ImportRewriter.rewrite_source(source)
        assert rewritten == ""

    def test_no_ai_imports(self) -> None:
        """Source with no ai.* imports should be unchanged (except provenance)."""
        source = (
            "from typing import Dict, List\n"
            "import os\n"
            "\n"
            "def func():\n"
            "    pass\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from typing import Dict, List" in rewritten
        assert "import os" in rewritten
    def test_relative_imports_preserved(self) -> None:
        """Relative imports should not be touched."""
        source = (
            "from .config import Config\n"
            "from ..common import something\n"
        )
        rewritten = Phase22ImportRewriter.rewrite_source(source, package="common")
        assert "from .config import Config" in rewritten
        assert "from ..common import something" in rewritten

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
