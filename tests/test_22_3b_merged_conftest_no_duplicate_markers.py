"""Phase 22.3b — Proof that merged conftest has no duplicate markers."""

from __future__ import annotations

import re
from pathlib import Path


def test_22_3b_no_duplicate_markers_in_root_conftest() -> None:
    """Verify that pytest markers are not registered twice in the root conftest.
    
    This prevents pytest warnings like:
      "already registered at /path/to/conftest.py:123"
    """
    root_conftest = Path(__file__).parent.parent / "tests" / "conftest.py"
    content = root_conftest.read_text()
    
    # Find all addinivalue_line calls for markers
    marker_lines = re.findall(
        r'config\.addinivalue_line\(\s*"markers",\s*"([a-zA-Z_][a-zA-Z0-9_-]*)',
        content,
    )
    
    # Check for duplicates
    unique_markers = set(marker_lines)
    if len(marker_lines) != len(unique_markers):
        duplicates = [m for m in unique_markers if marker_lines.count(m) > 1]
        raise AssertionError(f"Duplicate markers registered: {duplicates}")


def test_22_3b_all_expected_markers_present() -> None:
    """Verify that expected markers are registered in consolidated conftest.
    
    Markers can be registered in two places:
    1. pyproject.toml in the `markers` list
    2. conftest.py via `config.addinivalue_line("markers", ...)`
    
    After consolidation, we expect core markers (live, cpu_only, slow, integration, chaos)
    to be in conftest; others may be in pyproject.toml only.
    """
    root_conftest = Path(__file__).parent.parent / "tests" / "conftest.py"
    content = root_conftest.read_text()
    
    # Expected markers in conftest (core markers)
    expected = {"live", "cpu_only", "slow", "integration", "chaos"}
    
    # Find all markers registered via config.addinivalue_line in conftest
    registered = set(
        re.findall(
            r'config\.addinivalue_line\(\s*"markers",\s*"([a-zA-Z_][a-zA-Z0-9_-]*)',
            content,
        )
    )
    
    missing = expected - registered
    if missing:
        raise AssertionError(f"Missing markers in conftest: {missing}")
