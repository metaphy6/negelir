"""Phase 18.7 — Repo-root lint config canonical (ledger #27).

The canonical lint configs pyproject.toml and .golangci.yml must exist
at the repo root and be properly configured.
"""

from __future__ import annotations

from pathlib import Path


def test_repo_root_lint_config_canonical() -> None:
    """Verify canonical lint configs exist at repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # Check pyproject.toml exists and has expected sections
    pyproject = repo_root / "pyproject.toml"
    assert pyproject.exists(), "Root pyproject.toml must exist"
    content = pyproject.read_text(encoding="utf-8")
    assert "[tool.pytest" in content or "[tool" in content, \
        "pyproject.toml must have tool configuration"
    
    # Check .golangci.yml exists
    golangci = repo_root / ".golangci.yml"
    assert golangci.exists(), "Root .golangci.yml must exist"
    go_content = golangci.read_text(encoding="utf-8")
    assert "linters:" in go_content or "issues:" in go_content, \
        ".golangci.yml must have linter configuration"
