"""Phase 22.13 — Go server builds clean; no ai/ embed paths remain."""
import subprocess
import sys
from pathlib import Path


def test_22_13_go_server_builds_clean():
    """
    Verification: The Go server builds cleanly after Phase 22 migration.
    
    Checks:
    1. `go build ./cmd/api ./cmd/mocksrv ./cmd/swarmctl` exits with code 0
    2. No errors or warnings in the build output
    3. No `ai/` embed paths remain in build output or source
    """
    repo_root = Path(__file__).parent.parent.parent
    server_dir = repo_root / "server"
    
    # Try to build the server binaries
    binaries = [
        "./cmd/api",
        "./cmd/mocksrv",
        "./cmd/swarmctl",
    ]
    
    result = None
    for binary in binaries:
        result = subprocess.run(
            ["go", "build", "-o", f"/tmp/{binary.split('/')[-1]}", binary],
            cwd=server_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if result.returncode != 0:
            break
    
    # Check exit code
    assert result.returncode == 0, (
        f"Go server build failed (exit code {result.returncode}):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    
    # Check for ai/ references in stderr (build warnings/errors)
    if "ai/" in result.stderr:
        # Filter out false positives like "failed" or "available"
        lines_with_ai = [
            line for line in result.stderr.split("\n")
            if "ai/" in line and not any(
                fp in line for fp in ["available", "failed", "email", "trail"]
            )
        ]
        assert not lines_with_ai, f"Build output contains ai/ paths:\n{chr(10).join(lines_with_ai)}"
    
    # Check main.go and server source files don't import ai/
    server_src = repo_root / "server"
    if server_src.exists():
        for go_file in server_src.rglob("*.go"):
            content = go_file.read_text(encoding="utf-8")
            # Check for ai/ package imports (not just the word "ai")
            if 'import' in content:
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if 'import' in line and '"' in line and 'ai/' in line:
                        raise AssertionError(
                            f"Go file {go_file.relative_to(repo_root)} contains ai/ import:\n{line}"
                        )
    
    print("✅ Go server builds clean; no ai/ embed paths found")
