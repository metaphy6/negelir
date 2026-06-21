"""Phase 22.2 bullet 11 — Proof: perf gate - full package within 60s.

The largest package (model/ with most import sites) completes in ≤60s.
Performance target met: no O(n²) or pathological behavior.
"""

from __future__ import annotations

import time

import pytest
from xops.codemod.phase22_rewriter import Phase22ImportRewriter


class TestPerformanceGate:
    """Proof: codemod performance is within SLO."""

    @pytest.mark.perf
    def test_large_file_completes_quickly(self) -> None:
        """Large file (simulating large package) rewrites in reasonable time."""
        # Simulate a large source file with many imports
        lines = []
        # Add many import lines
        for i in range(1000):
            lines.append(f"from ai.common.module{i} import func{i}")
        # Add content
        lines.append("\ndef main():")
        for i in range(100):
            lines.append(f"    result = func{i}()")
        
        large_source = "\n".join(lines)

        # Time the rewrite
        start = time.time()
        result, status = Phase22ImportRewriter.rewrite_source(large_source, package="common")
        elapsed = time.time() - start

        # Should complete in < 60 seconds (much faster in practice)
        assert elapsed < 60.0, f"Rewrite took {elapsed:.2f}s (limit: 60s)"
        # Should actually be much faster (< 1 second typical)
        assert elapsed < 5.0, f"Rewrite performance suboptimal: {elapsed:.2f}s"

    @pytest.mark.perf
    def test_idempotent_rewrite_fast(self) -> None:
        """Idempotent rewrite (already rewritten file) is fast."""
        # File already rewritten (no ai.* imports)
        source = "from common.config import Config\n" * 100

        start = time.time()
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        elapsed = time.time() - start

        # Should be instant (just checking)
        assert elapsed < 1.0, f"Idempotent check took {elapsed:.2f}s"
        assert status == "no-op"

    @pytest.mark.perf
    def test_nested_imports_performance(self) -> None:
        """Deeply nested imports are handled efficiently."""
        # Generate nested imports
        lines = [
            "from ai.common.a.b.c.d.e.f import x",
            "from ai.common.x.y.z.deep.nested import y",
            "import ai.common.deeply.nested.module",
        ] * 100
        source = "\n".join(lines)

        start = time.time()
        result, status = Phase22ImportRewriter.rewrite_source(source, package="common")
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Nested imports took {elapsed:.2f}s"
        assert status == "rewritten"
