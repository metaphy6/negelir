"""Phase 22.5 proof test — Go parity test source paths updated to new layout."""
from pathlib import Path


def test_22_5_go_parity_test_paths_updated() -> None:
    """Verify embedded_parity_test.go canonical paths use new layout."""
    parity_test = Path(__file__).parent.parent / "server" / "internal" / "sec" / "embedded_parity_test.go"
    assert parity_test.exists(), f"embedded_parity_test.go not found"

    content = parity_test.read_text(encoding="utf-8")
    
    # New paths should be present
    assert 'swarm/sdk/schemas/qa.request.v1.json' in content, \
        "Must update to swarm/sdk/schemas/ path"
    assert 'common/security/injection_patterns.yaml' in content, \
        "Must update to common/security/ path"
    assert 'common/security/endpoint_costs.yaml' in content, \
        "Must update to common/security/ path"
    
    # Old paths should be removed
    assert 'ai/swarm/sdk/schemas' not in content, \
        "Old ai/swarm path must be removed"
    assert 'ai/common/security' not in content, \
        "Old ai/common path must be removed"
