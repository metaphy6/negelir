"""Phase 22.5 proof test — Go runtime path constant updated to new layout."""
from pathlib import Path
import re


def test_22_5_go_runtime_path_const_updated() -> None:
    """Verify defaultTRNormalizeSpecPath in sanitize.go uses new path."""
    sanitize_go = Path(__file__).parent.parent / "server" / "internal" / "sec" / "sanitize.go"
    assert sanitize_go.exists(), f"sanitize.go not found at {sanitize_go}"

    content = sanitize_go.read_text(encoding="utf-8")
    
    # The constant should now point to common/text/, not ai/common/text/
    assert 'const defaultTRNormalizeSpecPath = "common/text/tr_normalize_spec.json"' in content, \
        "defaultTRNormalizeSpecPath must be updated to new layout (common/text/...)"
    
    # Ensure old path is gone
    assert "ai/common/text/tr_normalize_spec.json" not in content, \
        "Old ai/ path must be removed from sanitize.go"
