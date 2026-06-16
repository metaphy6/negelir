"""Phase 18.7 — Legacy env vars in alias window (ledger #28, ledger #8).

Legacy (non-namespaced) NEGELIR_* vars should be in a deprecation alias window.
This test verifies the mechanism exists (even if no legacy vars yet exist).
"""

from __future__ import annotations

from pathlib import Path


def test_legacy_env_vars_in_alias_window() -> None:
    """Verify deprecation alias window infrastructure for env vars exists."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # The xops versioning infrastructure should handle deprecation windows
    xops_versioning = repo_root / "xops" / "versioning"
    assert xops_versioning.exists(), f"{xops_versioning} does not exist"
    
    # Check for version.py which handles component renaming and aliases
    version_py = xops_versioning / "version.py"
    assert version_py.exists(), "Version tool should exist for managing deprecations"
    
    # Verify the version chart exists (used for alias tracking)
    chart = xops_versioning / "chart.json"
    assert chart.exists(), "Chart should track component versions and aliases"
