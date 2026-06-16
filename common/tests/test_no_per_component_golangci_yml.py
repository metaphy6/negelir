"""Phase 18.7 ledger #27 proof test: no per-component .golangci.yml."""

from pathlib import Path


def test_no_per_component_golangci_yml() -> None:
    """Only the root .golangci.yml is allowed; no per-component overrides."""
    root = Path("/home/tech/code/negelir")
    
    # Find all .golangci.yml files
    all_golangci = list(root.rglob(".golangci.yml"))
    
    # Filter out the root one
    non_root = [p for p in all_golangci if p != root / ".golangci.yml"]
    
    assert not non_root, f"Found per-component .golangci.yml files (forbidden):\n" + "\n".join(
        str(p) for p in non_root
    )
    
    # Ensure root .golangci.yml exists
    assert (root / ".golangci.yml").exists(), "Root .golangci.yml not found"
    
    print("✓ Only root .golangci.yml present")


if __name__ == "__main__":
    test_no_per_component_golangci_yml()
