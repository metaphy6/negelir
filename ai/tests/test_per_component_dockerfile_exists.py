"""Phase 18.4 — Per-component Dockerfile existence test."""
from __future__ import annotations

from pathlib import Path


def test_per_component_dockerfile_exists() -> None:
    """Each component (ai, server) has a Dockerfile."""
    components = ["ai", "server"]
    repo_root = Path(__file__).parent.parent.parent

    for component in components:
        dockerfile = repo_root / component / "Dockerfile"
        assert dockerfile.exists(), f"{component}/Dockerfile does not exist"
        assert dockerfile.stat().st_size > 0, f"{component}/Dockerfile is empty"
