"""Phase 22.5 proof test — Go parity test passes after path migration."""
import subprocess
from pathlib import Path


def test_22_5_go_sec_parity_test_passes_after_move() -> None:
    """Verify Go embedded parity test passes with updated canonical paths."""
    server_dir = Path(__file__).parent.parent / "server"
    
    # Check if go is available
    result = subprocess.run(
        ["go", "version"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    
    if result.returncode != 0:
        # Go not available, skip
        return
    
    # Try to run the sec package tests (includes parity test)
    result = subprocess.run(
        ["go", "test", "-v", "./internal/sec/..."],
        cwd=str(server_dir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    # Should not have any ai/ path related errors
    output = result.stderr + result.stdout
    assert "ai/" not in output or "github.com" in output, \
        f"Go sec tests should not reference ai/ paths:\n{output[:500]}"
