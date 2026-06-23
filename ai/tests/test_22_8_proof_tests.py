"""Phase 22.8 — Proof tests: Mock absorption and compose cleanup are complete."""

import subprocess
import sys
from pathlib import Path


def run_proof_test(test_module_path: str, test_name: str) -> bool:
    """Run a proof test and return whether it passed."""
    result = subprocess.run(
        [sys.executable, test_module_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"❌ {test_name} FAILED")
        print(result.stdout)
        print(result.stderr)
        return False
    print(f"✅ {test_name} passed")
    return True


def test_22_8_proof_all_pass():
    """Run all Phase 22.8 proof tests."""
    repo_root = Path(__file__).parent.parent.parent
    test_dir = repo_root / "ai" / "tests"
    tests_root = repo_root / "tests"
    
    proof_tests = [
        (str(test_dir / "test_22_8_compose_profiles.py"), "test_22_8_compose_mock_overlay_removed"),
        (str(test_dir / "test_22_8_server_mode_mocksrv.py"), "test_22_8_server_mode_mocksrv_works_without_overlay"),
        (str(test_dir / "test_22_8_compose_all_profile.py"), "test_22_8_make_up_all_without_mock_overlay"),
        (str(tests_root / "test_22_4_no_datasource_folder_at_root.py"), "test_22_8_no_datasource_folder_regression"),
    ]
    
    results = []
    for test_path, test_name in proof_tests:
        passed = run_proof_test(test_path, test_name)
        results.append((test_name, passed))
    
    failed = [name for name, passed in results if not passed]
    if failed:
        raise AssertionError(f"Proof tests failed: {failed}")
    
    print("\n" + "=" * 60)
    print("✅ ALL PHASE 22.8 PROOF TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    test_22_8_proof_all_pass()
