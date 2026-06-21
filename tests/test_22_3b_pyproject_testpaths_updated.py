"""Phase 22.3b — Proof that pyproject.toml testpaths is updated."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_22_3b_testpaths_updated_in_pyproject() -> None:
    """Verify that pyproject.toml testpaths no longer includes ai/tests."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())
    
    testpaths = config.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths", [])
    
    # ai/tests should NOT be in testpaths anymore
    if "ai/tests" in testpaths:
        raise AssertionError(
            f"ai/tests should be removed from testpaths. Got: {testpaths}"
        )
    
    # tests SHOULD be in testpaths (unless it's been merged differently)
    if "tests" not in testpaths:
        raise AssertionError(
            f"tests should be in testpaths. Got: {testpaths}"
        )


def test_22_3b_no_duplicate_testpaths() -> None:
    """Verify no duplicate entries in testpaths."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text())
    
    testpaths = config.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths", [])
    
    if len(testpaths) != len(set(testpaths)):
        duplicates = [p for p in set(testpaths) if testpaths.count(p) > 1]
        raise AssertionError(f"Duplicate testpaths: {duplicates}")
