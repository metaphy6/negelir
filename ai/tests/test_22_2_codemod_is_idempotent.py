"""Phase 22.2 bullet 7 — Idempotency tests for the codemod engine.

Verifies:
1. Running the codemod twice on the same file produces no further diff
2. The engine detects already-rewritten files via absence of ai.* imports
3. Status is "no-op" on second and subsequent runs
4. Stability over multiple consecutive runs
"""

from __future__ import annotations

from pathlib import Path
from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestCodemodIdempotency:
    """Test idempotency of the Phase 22 codemod engine."""

    def test_second_run_produces_no_op(self) -> None:
        """Verify that running the codemod twice produces a no-op on the second run."""
        source_with_ai_imports = '''"""Test module with ai.* imports."""
from ai.common.config import cfg
from ai.common.logger import get_logger
import ai.model

logger = get_logger(__name__)
'''
        
        # First run: should rewrite
        rewritten_1, status_1 = Phase22ImportRewriter.rewrite_source(source_with_ai_imports, package="common")
        assert status_1 == "rewritten", f"Expected 'rewritten', got {status_1}"
        assert rewritten_1 != source_with_ai_imports, "First run should produce changes"
        assert "from common.config import cfg" in rewritten_1, "First run should rewrite imports"
        assert "from ai." not in rewritten_1, "First run should remove ai.* imports"
        
        # Second run: should be no-op
        rewritten_2, status_2 = Phase22ImportRewriter.rewrite_source(rewritten_1, package="common")
        assert status_2 == "no-op", f"Expected 'no-op' on second run, got {status_2}"
        assert rewritten_2 == rewritten_1, "Second run should produce no changes"

    def test_already_rewritten_file_is_no_op(self) -> None:
        """Verify that a file with no ai.* imports is detected as already rewritten."""
        source_no_ai_imports = '''"""Test module with no ai.* imports."""
from common.config import cfg
from common.logger import get_logger
import common

logger = get_logger(__name__)
'''
        
        rewritten, status = Phase22ImportRewriter.rewrite_source(source_no_ai_imports, package="common")
        assert status == "no-op", f"Expected 'no-op' for already-rewritten file, got {status}"
        assert rewritten == source_no_ai_imports, "Already-rewritten file should have no changes"

    def test_mixed_imports_detected_as_needs_rewrite(self) -> None:
        """Verify that a file with mixed ai.* and regular imports is detected as needing rewrite."""
        source_mixed = '''"""Test module with mixed imports."""
from common.config import base_cfg
from ai.common.config import cfg
import common
import ai.nlp

cfg_instance = cfg
'''
        
        rewritten, status = Phase22ImportRewriter.rewrite_source(source_mixed, package="common")
        assert status == "rewritten", f"Expected 'rewritten' for mixed imports, got {status}"
        assert rewritten != source_mixed, "Mixed import file should be rewritten"
        assert "from common.config import cfg" in rewritten, "ai.* imports should be rewritten"

    def test_idempotency_over_five_runs(self) -> None:
        """Verify stability over multiple consecutive runs."""
        source = '''"""Test module."""
from ai.nlp.lexicon_loader import LexiconStore
from ai.nlp.normalizer import normalize_text
import ai.nlp
'''
        
        current = source
        
        # First run
        rewritten_1, status_1 = Phase22ImportRewriter.rewrite_source(current, package="nlp")
        assert status_1 == "rewritten"
        assert "from ai.nlp" not in rewritten_1
        assert "from nlp.lexicon_loader" in rewritten_1
        current = rewritten_1
        
        # Runs 2-5: all should be no-op
        for run_num in range(2, 6):
            rewritten_n, status_n = Phase22ImportRewriter.rewrite_source(current, package="nlp")
            assert status_n == "no-op", f"Run {run_num} should be no-op, got {status_n}"
            assert rewritten_n == current, f"Run {run_num} should produce no changes"
            # Don't update current; it should stay identical across all no-op runs

    def test_is_already_rewritten_method(self) -> None:
        """Test the is_already_rewritten() method directly."""
        rewriter = Phase22ImportRewriter()
        
        # Source with ai.* imports should NOT be considered rewritten
        source_with_ai = "from ai.common import cfg\nimport ai.model"
        assert not rewriter.is_already_rewritten(source_with_ai), \
            "Source with ai.* imports should not be considered rewritten"
        
        # Source without ai.* imports should be considered rewritten
        source_no_ai = "from common import cfg\nimport model"
        assert rewriter.is_already_rewritten(source_no_ai), \
            "Source without ai.* imports should be considered rewritten"
        
        # Empty source should be considered rewritten
        empty = ""
        assert rewriter.is_already_rewritten(empty), \
            "Empty source should be considered rewritten"
        
        # Source with commented import is considered as needing rewrite
        # (because regex matches in comments too)
        source_with_commented_import = "# from ai.common import cfg"
        assert not rewriter.is_already_rewritten(source_with_commented_import), \
            "Source with commented ai.* imports is detected by regex"

    def test_comments_with_ai_not_blocking_rewrite(self) -> None:
        """Verify that comments or strings mentioning 'ai.' don't prevent no-op detection."""
        source = '''"""Module docstring mentioning ai.common.utils."""
# This code was generated from ai/common/utils.py
# See ai.model for details

from common.config import cfg
from model import Model
'''
        
        rewritten, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        # Comments and docstrings mentioning ai. should NOT block the no-op detection
        # because we only look for `from ai.` and `import ai.` statements
        assert status == "no-op", f"Comments/docstrings should not prevent no-op, got {status}"
        assert rewritten == source, "File with no ai.* imports should not be modified"

    def test_rewrite_method_returns_tuple(self) -> None:
        """Verify that rewrite() method returns a tuple of (source, status)."""
        source = "from ai.common import cfg"
        rewriter = Phase22ImportRewriter()
        
        result = rewriter.rewrite(source)
        assert isinstance(result, tuple), "rewrite() should return a tuple"
        assert len(result) == 2, "rewrite() should return a 2-tuple"
        
        rewritten, status = result
        assert isinstance(rewritten, str), "First element should be str"
        assert isinstance(status, str), "Second element should be str"
        assert status in {"rewritten", "no-op"}, f"Status should be 'rewritten' or 'no-op', got {status}"


class TestCodemodAlreadyRewrittenDetection:
    """Test detection of already-rewritten files via absence of ai.* imports."""

    def test_from_ai_import_variants(self) -> None:
        """Test various 'from ai.' import patterns are detected."""
        rewriter = Phase22ImportRewriter()
        
        patterns = [
            "from ai.common import cfg",
            "from ai.common.config import Config",
            "from ai.nlp.lexicon_loader import LexiconStore",
            "from ai.model import FeatureExtractor",
            "from ai.scraper.extractors import Extractor",
        ]
        
        for pattern in patterns:
            assert not rewriter.is_already_rewritten(pattern), \
                f"Pattern '{pattern}' should be detected as needing rewrite"

    def test_import_ai_variants(self) -> None:
        """Test various 'import ai.' patterns are detected."""
        rewriter = Phase22ImportRewriter()
        
        patterns = [
            "import ai.common",
            "import ai.nlp",
            "import ai.model as model",
            "import ai.scraper",
        ]
        
        for pattern in patterns:
            assert not rewriter.is_already_rewritten(pattern), \
                f"Pattern '{pattern}' should be detected as needing rewrite"

    def test_no_ai_imports(self) -> None:
        """Test that files without ai.* imports are detected as rewritten."""
        rewriter = Phase22ImportRewriter()
        
        sources = [
            "from common import cfg",
            "from nlp.lexicon_loader import LexiconStore",
            "import model",
            "import scraper",
            """
# This file was generated from ai/common/utils.py (no import statements)
from common.utils import helper
""",
        ]
        
        for source in sources:
            assert rewriter.is_already_rewritten(source), \
                f"Source should be detected as rewritten:\n{source}"

    def test_type_checking_imports_detected(self) -> None:
        """Test TYPE_CHECKING imports with ai.* are detected."""
        rewriter = Phase22ImportRewriter()
        
        source_with_type_checking = '''
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.common.config import Config
'''
        
        # TYPE_CHECKING imports have the same patterns
        assert not rewriter.is_already_rewritten(source_with_type_checking), \
            "TYPE_CHECKING imports with ai.* should be detected"

COMMANDS = {
    "TestCodemodIdempotency": TestCodemodIdempotency,
    "TestCodemodAlreadyRewrittenDetection": TestCodemodAlreadyRewrittenDetection,
}

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
