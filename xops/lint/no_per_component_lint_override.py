#!/usr/bin/env python3
"""
Phase 18.7 ledger #27 — no per-component lint override lint.

Asserts that pyproject.toml and .golangci.yml are only at the repo root,
not per-component. All lint config is canonical at the root.
"""

import sys
from pathlib import Path


def lint_no_per_component_overrides() -> int:
    """Check for forbidden per-component lint config files.
    
    Returns:
        0 if no violations; 1 otherwise.
    """
    root = Path(__file__).resolve().parent.parent.parent
    violations = []
    
    # Forbidden patterns: pyproject.toml and .golangci.yml outside root
    for pyproject in root.rglob("pyproject.toml"):
        if pyproject != root / "pyproject.toml":
            violations.append(str(pyproject))
    
    for golangci in root.rglob(".golangci.yml"):
        if golangci != root / ".golangci.yml":
            violations.append(str(golangci))
    
    if violations:
        print("Per-component lint config files found (forbidden by ledger #27):", file=sys.stderr)
        for path in violations:
            print(f"  {path}", file=sys.stderr)
        print("\nAll lint config must be at the repo root.", file=sys.stderr)
        return 1
    
    # Check that root files exist
    root_pyproject = root / "pyproject.toml"
    root_golangci = root / ".golangci.yml"
    
    if not root_pyproject.exists():
        print(f"ERROR: {root_pyproject} not found (required)", file=sys.stderr)
        return 1
    
    if not root_golangci.exists():
        print(f"ERROR: {root_golangci} not found (required)", file=sys.stderr)
        return 1
    
    print("✓ Lint config is canonical at repo root.")
    return 0


if __name__ == "__main__":
    sys.exit(lint_no_per_component_overrides())
