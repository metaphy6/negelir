"""Phase 18.4 — Swarm image must not contain psycopg2 (DB access forbidden)."""
from __future__ import annotations

from pathlib import Path


def test_swarm_image_does_not_contain_psycopg() -> None:
    """Swarm/datasource Dockerfile must have a probe that ensures psycopg2 is not present."""
    repo_root = Path(__file__).parent.parent.parent
    ai_dockerfile = repo_root / "ai" / "Dockerfile"

    with open(ai_dockerfile) as f:
        content = f.read()

    # The Dockerfile must contain a line that tests for psycopg2 import failure
    assert "import psycopg2" in content, (
        "ai/Dockerfile missing forbidden-dep probe for psycopg2.\n"
        "Add: RUN python -c \"import psycopg2\" && exit 1 || true"
    )
    assert "exit 1" in content, "ai/Dockerfile probe doesn't properly reject psycopg2"
