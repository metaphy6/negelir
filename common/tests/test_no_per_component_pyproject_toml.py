"""Phase 18.7 ledger #27 proof test: no per-component pyproject.toml."""

from pathlib import Path


def test_no_per_component_pyproject_toml() -> None:
    """Only the root pyproject.toml is allowed; no per-component overrides."""
    root = Path("/home/tech/code/negelir")
    
    # Find all pyproject.toml files
    all_pyproject = list(root.rglob("pyproject.toml"))
    
    # Filter out the root one
    non_root = [p for p in all_pyproject if p != root / "pyproject.toml"]
    
    assert not non_root, f"Found per-component pyproject.toml files (forbidden):\n" + "\n".join(
        str(p) for p in non_root
    )
    
    # Ensure root pyproject.toml exists
    assert (root / "pyproject.toml").exists(), "Root pyproject.toml not found"
    
    print("✓ Only root pyproject.toml present")


if __name__ == "__main__":
    test_no_per_component_pyproject_toml()
