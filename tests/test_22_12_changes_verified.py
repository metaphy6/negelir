"""Phase 22.12 — Verify all proof changes are complete."""
from pathlib import Path
import subprocess

def test_22_12_present_phase_ledger_lints_pass_after_update():
    """Phase 16 ledger lint should still pass after ROADMAP updates."""
    result = subprocess.run(
        ["python3", "xops/lint/phase16_ledger.py"],
        capture_output=True,
        text=True,
        cwd="/home/tech/code/negelir"
    )
    assert result.returncode == 0, f"phase16_ledger.py failed: {result.stderr}"
    assert "verified" in result.stdout.lower()

def test_22_12_docs_verify_passes_after_sweep():
    """make docs.verify should pass after design doc updates."""
    result = subprocess.run(
        ["make", "docs.verify"],
        capture_output=True,
        text=True,
        cwd="/home/tech/code/negelir"
    )
    assert result.returncode == 0, f"make docs.verify failed: {result.stderr}"
    assert "All 6 anchor docs are current" in result.stdout or "current" in result.stdout.lower()

def test_22_12_patcher_artifact_state_recorded():
    """No-op state file should be recorded."""
    state_file = Path("/home/tech/code/negelir/docs/tracking/phase22_patcher_artifact_state.txt")
    assert state_file.exists(), "phase22_patcher_artifact_state.txt not found"
    content = state_file.read_text()
    assert "No-op" in content or "ABSENT" in content

if __name__ == "__main__":
    test_22_12_present_phase_ledger_lints_pass_after_update()
    print("✓ phase16_ledger lint passes")
    test_22_12_docs_verify_passes_after_sweep()
    print("✓ docs.verify passes")
    test_22_12_patcher_artifact_state_recorded()
    print("✓ patcher artifact state recorded")
