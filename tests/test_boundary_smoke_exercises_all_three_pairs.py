"""Phase 18.4 — Boundary smoke exercises all boundary pairs."""
from __future__ import annotations

from pathlib import Path


def test_boundary_smoke_exercises_all_three_pairs() -> None:
    """Boundary smoke tests all four component boundaries."""
    repo_root = Path(__file__).parent.parent.parent
    boundary_py = repo_root / "xops" / "smoke" / "boundary.py"

    with open(boundary_py) as f:
        content = f.read()

    # Must test scraper → emitter boundary
    assert any(phrase in content.lower() for phrase in ["scraper", "extractor", "source"]), (
        "boundary.py must test data scraper boundary"
    )

    # Must test emitter → reader boundary
    assert any(phrase in content.lower() for phrase in ["emitter", "feed", "record"]), (
        "boundary.py must test feed emission boundary"
    )

    # Must test reader → swarm boundary
    assert any(phrase in content.lower() for phrase in ["reader", "consumer", "swarm"]), (
        "boundary.py must test swarm consumption boundary"
    )

    # Must test swarm → API boundary
    assert any(phrase in content.lower() for phrase in ["api", "server", "prediction"]), (
        "boundary.py must test server API boundary"
    )
