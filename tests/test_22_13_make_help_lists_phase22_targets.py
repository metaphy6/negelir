"""Phase 22.13 — Verify make help includes phase22 targets."""
import subprocess
from pathlib import Path


def test_22_13_make_help_lists_phase22_targets():
    """
    Verification: `make help` output includes Phase 22 target documentation.
    
    Phase 22 adds new targets like:
    - make phase22.rehearse
    - make phase22.burn-in.status
    - make phase22.rollback
    
    These must be documented in `make help` output under a "phase22" section.
    """
    repo_root = Path(__file__).parent.parent.parent
    
    result = subprocess.run(
        ["make", "help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    assert result.returncode == 0, f"make help failed: {result.stderr}"
    
    help_text = result.stdout + result.stderr
    
    # Check for Phase 22 targets in the output
    phase22_keywords = [
        "phase22",
        "phase22.rehearse",
        "phase22.burn-in",
        "phase22.rollback",
    ]
    
    found = []
    missing = []
    for keyword in phase22_keywords:
        if keyword in help_text.lower():
            found.append(keyword)
        else:
            missing.append(keyword)
    
    assert not missing, (
        f"make help output missing Phase 22 targets: {missing}\n"
        f"Found: {found}"
    )
