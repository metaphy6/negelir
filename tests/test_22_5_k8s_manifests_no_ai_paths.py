"""Phase 22.5 proof test — k8s manifests have no ai/ path references."""
from subprocess import run
from pathlib import Path


def test_22_5_k8s_manifests_no_ai_paths() -> None:
    """Verify xops/lint/phase22_k8s_paths.py linter passes."""
    linter = Path(__file__).parent.parent / "xops" / "lint" / "phase22_k8s_paths.py"
    assert linter.exists(), f"k8s linter not found at {linter}"
    
    result = run(["python3", str(linter)], cwd=str(Path(__file__).parent.parent))
    assert result.returncode == 0, "k8s manifest linter must exit 0 (no ai/ references)"
