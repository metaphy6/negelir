"""Phase 22.12 — Verify `make docs.verify` passes after ROADMAP path sweep."""
import subprocess
from pathlib import Path


def test_22_12_docs_verify_passes_after_sweep():
    """
    Proof test: After the Phase 22 ROADMAP path reference sweep,
    `make docs.verify` should exit 0 (success).
    
    This ensures all documentation consistency checks pass after the updates.
    """
    repo_root = Path(__file__).parent.parent.parent
    
    # Run make docs.verify
    result = subprocess.run(
        ["make", "docs.verify"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    
    assert result.returncode == 0, (
        f"make docs.verify failed with exit code {result.returncode}"
    )


if __name__ == "__main__":
    test_22_12_docs_verify_passes_after_sweep()
    print("✅ make docs.verify passes after path sweep")
