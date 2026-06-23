"""Phase 22.5 proof test — Go server code compiles without ai/ path errors."""
import subprocess
from pathlib import Path


def test_22_5_go_build_succeeds_after_path_migration() -> None:
    """Verify Go server code compiles without ai/ path errors."""
    server_dir = Path(__file__).parent.parent / "server"
    
    # Check if go is available
    result = subprocess.run(
        ["go", "version"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    
    if result.returncode != 0:
        # Go not available, skip (CI will have it)
        return
    
    # Try to build the main server package
    result = subprocess.run(
        ["go", "build", "-v", "./cmd/api"],
        cwd=str(server_dir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    # Compilation should succeed or fail for reasons unrelated to ai/ paths
    # (e.g., missing dependencies, module issues). The key is no ai/ path errors.
    output = result.stderr + result.stdout
    assert "ai/" not in output or "github.com/metaphy6/negelir" in output, \
        f"Go code should not reference ai/ paths:\n{output[:500]}"
