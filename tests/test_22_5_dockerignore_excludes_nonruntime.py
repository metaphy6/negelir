"""Phase 22.5 proof test — .dockerignore excludes non-runtime paths."""
from pathlib import Path


def test_22_5_dockerignore_excludes_nonruntime() -> None:
    """Verify .dockerignore exists and excludes required paths."""
    dockerignore = Path(__file__).parent.parent / ".dockerignore"
    assert dockerignore.exists(), f".dockerignore not found at {dockerignore}"

    content = dockerignore.read_text(encoding="utf-8")
    required_exclusions = ["xops/", "docs/", "data/", "infra/", "migrations/", "server/", "*.md", ".git/"]
    
    for exclusion in required_exclusions:
        assert exclusion in content, f".dockerignore must exclude '{exclusion}'"
