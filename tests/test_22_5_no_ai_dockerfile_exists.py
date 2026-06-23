"""Phase 22.5 proof test — ai/Dockerfile must not exist after root Dockerfile merge."""
from pathlib import Path


def test_22_5_no_ai_dockerfile_exists() -> None:
    """Verify ai/Dockerfile was deleted after content merged to root."""
    ai_dockerfile = Path(__file__).parent.parent / "ai" / "Dockerfile"
    assert not ai_dockerfile.exists(), f"ai/Dockerfile should not exist; found at {ai_dockerfile}"
