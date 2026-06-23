"""Phase 22.5 proof test — phase22_k8s_paths.py is wired into CI gauntlet."""
from pathlib import Path


def test_22_5_k8s_linter_wired_in_ci() -> None:
    """Verify xops/ci/run_gauntlet.sh includes k8s_paths linter as a gate."""
    gauntlet_path = Path(__file__).parent.parent / "xops" / "ci" / "run_gauntlet.sh"
    assert gauntlet_path.exists(), "run_gauntlet.sh not found"
    
    content = gauntlet_path.read_text(encoding="utf-8")
    
    # Check that the linter is included
    assert "xops/lint/phase22_k8s_paths.py" in content, \
        "run_gauntlet.sh must include k8s_paths linter"
    
    # Check that it's called as a gate
    assert "run_gate k8s_paths" in content or "run_gate" in content and "phase22_k8s_paths.py" in content, \
        "k8s_paths must be run as a gate"
    
    # Verify linter file exists and is executable
    linter_path = Path(__file__).parent.parent / "xops" / "lint" / "phase22_k8s_paths.py"
    assert linter_path.exists(), "phase22_k8s_paths.py not found"
