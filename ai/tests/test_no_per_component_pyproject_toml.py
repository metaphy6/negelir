"""Phase 18.7 — No per-component pyproject.toml (ledger #27).

Only one project-wide pyproject.toml at repo root is allowed.
Per-component overrides are forbidden.
"""

from __future__ import annotations

from pathlib import Path


def test_no_per_component_pyproject_toml() -> None:
    """Verify no per-component pyproject.toml files exist."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # Find the canonical root pyproject.toml
    root_pyproject = repo_root / "pyproject.toml"
    assert root_pyproject.exists(), "Root pyproject.toml must exist"
    
    # Search for any per-component pyproject.toml files
    # Common component roots: ai/, datasource/, swarm/, server/, common/
    component_roots = [
        "ai", "datasource", "swarm", "server", "common",
        "xops", "infra", "migrations", "docs"
    ]
    
    violations = []
    for comp_root in component_roots:
        comp_path = repo_root / comp_root
        if not comp_path.exists():
            continue
        
        # Search for pyproject.toml in subdirectories (not the component root itself)
        for pyproj in comp_path.rglob("pyproject.toml"):
            # Skip the root one
            if pyproj != root_pyproject:
                violations.append(pyproj)
    
    if violations:
        msg = "Per-component pyproject.toml files are forbidden:\n"
        for v in violations:
            msg += f"  {v}\n"
        raise AssertionError(msg)
