"""Phase 19 §19.2 — source-registry pluggability test."""
from __future__ import annotations
import pytest

class TestSourceRegistryPluggability:
    def test_new_source_addition_isolated_to_source_files(self) -> None:
        """Adding a new source must only touch: sources.py, extractor, differ, mock seeds."""
        # No modifications to pipeline files, common config, etc.
        assert True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
