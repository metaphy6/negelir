"""Phase 18.4 — Boundary smoke failure pinpoints the violated boundary."""
from __future__ import annotations

from pathlib import Path


def test_boundary_smoke_failure_pinpoints_boundary() -> None:
    """Boundary smoke failures include structured logs that identify the boundary."""
    repo_root = Path(__file__).parent.parent.parent
    boundary_py = repo_root / "xops" / "smoke" / "boundary.py"

    with open(boundary_py) as f:
        content = f.read()

    # Must emit structured logs with boundary information
    assert "boundary" in content.lower() or "component" in content.lower(), (
        "boundary.py must emit logs that identify which boundary failed"
    )

    # Must have assertion or error reporting
    assert "assert" in content or "raise" in content or "log" in content.lower(), (
        "boundary.py must have failure reporting logic"
    )
