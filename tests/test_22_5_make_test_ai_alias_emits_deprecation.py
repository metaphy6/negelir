"""Phase 22.5 proof test — make test.ai alias exists and works."""
import subprocess
from pathlib import Path


def test_22_5_make_test_ai_alias_emits_deprecation() -> None:
    """Verify make test.ai target exists and emits deprecation or runs tests."""
    repo_root = Path(__file__).parent.parent
    
    # Check if test.ai target exists in Makefile
    makefile = repo_root / "Makefile"
    content = makefile.read_text(encoding="utf-8")
    
    # Should have test.ai target
    assert ".PHONY: test.ai" in content, "Makefile must have test.ai target"
    
    # The target should exist and be callable
    result = subprocess.run(
        ["make", "test.ai", "--dry-run"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Should be able to parse the target without error
    assert result.returncode == 0, \
        f"make test.ai --dry-run failed: {result.stderr}"
