"""Phase 18.7 — No per-component .golangci.yml (ledger #27).

Only one project-wide .golangci.yml at repo root is allowed.
Per-component overrides are forbidden.
"""

from __future__ import annotations

from pathlib import Path


def test_no_per_component_golangci_yml() -> None:
    """Verify no per-component .golangci.yml files exist."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # Find the canonical root .golangci.yml
    root_golangci = repo_root / ".golangci.yml"
    assert root_golangci.exists(), "Root .golangci.yml must exist"
    
    # Search for any per-component .golangci.yml files
    component_roots = [
        "server", "xops", "infra"  # Go-related directories
    ]
    
    violations = []
    for comp_root in component_roots:
        comp_path = repo_root / comp_root
        if not comp_path.exists():
            continue
        
        for golangci in comp_path.rglob(".golangci.yml"):
            if golangci != root_golangci:
                violations.append(golangci)
    
    if violations:
        msg = "Per-component .golangci.yml files are forbidden:\n"
        for v in violations:
            msg += f"  {v}\n"
        raise AssertionError(msg)
