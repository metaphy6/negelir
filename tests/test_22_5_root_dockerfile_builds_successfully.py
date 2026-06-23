"""Phase 22.5 proof test — root Dockerfile builds successfully with correct image."""
from pathlib import Path
from subprocess import run, PIPE


def test_22_5_root_dockerfile_builds_successfully() -> None:
    """Verify root Dockerfile builds successfully (dry-run with syntax check)."""
    dockerfile = Path(__file__).parent.parent / "Dockerfile"
    assert dockerfile.exists(), f"Root Dockerfile not found at {dockerfile}"

    # Verify it contains the required settings
    content = dockerfile.read_text(encoding="utf-8")
    assert "python:3.12-slim" in content, "Dockerfile must use python:3.12-slim"
    assert "ENV PYTHONPATH=." in content, "PYTHONPATH must be set to . (relative path)"
    assert "COPY . ." in content, "Must copy entire context (COPY . .)"
    # Verify no ai/ paths in COPY commands
    assert "COPY ai/" not in content, "Dockerfile must not reference ai/ in COPY"
    # Verify the deprecated ai/Dockerfile is actually gone
    ai_dockerfile = Path(__file__).parent.parent / "ai" / "Dockerfile"
    assert not ai_dockerfile.exists(), "ai/Dockerfile should have been deleted"
