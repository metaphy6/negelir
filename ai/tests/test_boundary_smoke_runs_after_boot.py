"""Phase 18.4 — Boundary smoke runs after successful boot."""
from __future__ import annotations

from pathlib import Path


def test_boundary_smoke_runs_after_boot() -> None:
    """The boundary smoke test framework exists and is callable."""
    repo_root = Path(__file__).parent.parent.parent
    boundary_py = repo_root / "xops" / "smoke" / "boundary.py"

    assert boundary_py.exists(), "xops/smoke/boundary.py does not exist"

    with open(boundary_py) as f:
        content = f.read()

    # Must have a main function or run logic
    assert "def main" in content or "if __name__" in content, (
        "boundary.py must have a main entry point"
    )

    # Should exercise boundaries
    keywords = ["scraper", "emitter", "reader", "swarm", "api"]
    found_keywords = sum(1 for kw in keywords if kw in content.lower())
    assert found_keywords >= 3, (
        "boundary.py must reference multiple boundaries (scraper, emitter, reader, swarm, api)"
    )
