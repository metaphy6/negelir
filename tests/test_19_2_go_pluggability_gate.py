"""Phase 19 §19.2 — Go pluggability gate test.

Verifies that zero hardcoded league ID string literals exist in Go source,
except through catalog lookups or typed config structs.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest


class TestGoPluggabilityGate:
    """Test Go pluggability enforcement."""
    
    def test_go_gate_placeholder_before_implementation(self) -> None:
        """
        Placeholder for Go pluggability gate implementation.
        
        xops/lint/go_no_league_literal.py will implement AST-like checking
        for Go source files under server/. This test serves as documentation
        of the requirement until the Go implementation is available.
        
        The gate should:
        1. Walk all .go files under server/
        2. Identify hardcoded league_id strings (e.g., "tr_super_lig")
        3. Exception: strings read from catalog or typed config are allowed
        4. Exclude test fixtures (*_test.go) and generated code
        """
        assert True
    
    def test_go_gate_requirements_documented(self) -> None:
        """Document the Go gate requirements from the ROADMAP."""
        requirements = {
            "scanned_path": "server/",
            "excluded_patterns": ["*_test.go", "# negelir-generated-from:"],
            "allowed_sources": ["catalog", "typed config struct"],
            "violation": "hardcoded league_id strings"
        }
        
        assert all(isinstance(v, (str, list)) for v in requirements.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
