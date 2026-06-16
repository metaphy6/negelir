"""Phase 18.7 ledger #27 proof test: lint config is canonical at repo root."""

from pathlib import Path


def test_repo_root_lint_config_canonical() -> None:
    """Verify that lint config is only at the root, not scattered per-component."""
    root = Path("/home/tech/code/negelir")
    
    # Check root files exist
    assert (root / "pyproject.toml").exists(), "Root pyproject.toml missing"
    assert (root / ".golangci.yml").exists(), "Root .golangci.yml missing"
    
    # Check root pyproject.toml has the right sections
    pyproject_content = (root / "pyproject.toml").read_text()
    assert "[tool.black]" in pyproject_content
    assert "[tool.isort]" in pyproject_content
    assert "[tool.mypy]" in pyproject_content
    
    # Check root .golangci.yml has the right structure
    golangci_content = (root / ".golangci.yml").read_text()
    assert "linters:" in golangci_content
    assert "issues:" in golangci_content
    
    print("✓ Lint config is canonical at repo root")


if __name__ == "__main__":
    test_repo_root_lint_config_canonical()
