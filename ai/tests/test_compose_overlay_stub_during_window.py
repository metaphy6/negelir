"""Phase 18.4 — Compose overlay is a stub during deprecation window."""
from __future__ import annotations

from pathlib import Path


def test_compose_overlay_stub_during_window() -> None:
    """docker-compose.mock.yml is a deprecation stub, not functional."""
    repo_root = Path(__file__).parent.parent.parent
    overlay_file = repo_root / "docker-compose.mock.yml"

    assert overlay_file.exists(), "docker-compose.mock.yml must exist (as stub)"

    with open(overlay_file) as f:
        content = f.read()

    # Must have deprecation notice
    assert "deprecated" in content.lower() or "Phase 22" in content, (
        "docker-compose.mock.yml must have deprecation notice"
    )

    # Must tell users to use profiles instead
    assert "profile" in content.lower() or "mock" in content.lower(), (
        "docker-compose.mock.yml must reference the new 'mock' profile"
    )

    # Must not have functional service definitions
    assert "server-mock:" not in content and "nginx-mock:" not in content, (
        "docker-compose.mock.yml must not contain functional services"
    )
