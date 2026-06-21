"""Phase 22.1 bullet 3 — Preflight gate blocks when Phase 18 fails.

Tests that `make phase22.preflight` exits non-zero when Phase 18 isolation
gates are failing, preventing inadvertent Phase 22 migration start.

Per ROADMAP §22.1 and §22.1 DoD.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.lint.phase22_preflight import PreflightChecker


class TestPhase221PreflightGateBlocksOnPhase18Failure:
    """Preflight gate refuses to proceed if Phase 18 gates fail."""

    def test_preflight_blocks_when_isolation_check_fails(self):
        """Preflight exits non-zero when `make isolation.check` fails."""
        checker = PreflightChecker(verbose=False)
        
        # Mock subprocess to simulate isolation check failure
        with patch("subprocess.run") as mock_run:
            # First call (isolation.check) fails
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Isolation check failed: forbidden cross-component import detected",
            )
            
            result = checker.run_all_checks()
            
            # Should fail
            assert result != 0
            assert len(checker.failures) > 0
            assert any("isolation" in f.lower() for f in checker.failures)

    def test_preflight_blocks_when_forbidden_edge_lint_fails(self):
        """Preflight exits non-zero when forbidden-edge lints fail."""
        checker = PreflightChecker(verbose=False)
        
        with patch("subprocess.run") as mock_run:
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # isolation.check passes
                    return MagicMock(returncode=0, stdout="", stderr="")
                else:
                    # forbidden edge lint fails
                    return MagicMock(returncode=1, stdout="", stderr="Forbidden edge detected")
            
            mock_run.side_effect = run_side_effect
            
            result = checker.run_all_checks()
            
            # Should fail on forbidden-edge
            assert result != 0

    def test_preflight_requires_isolation_check_green_first(self):
        """Isolation check must pass before other checks run."""
        checker = PreflightChecker(verbose=False)
        
        # Verify isolation.check is called with correct make target
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            
            checker.check_isolation_gates()
            
            # Verify the call was to "make isolation.check"
            calls = mock_run.call_args_list
            assert any("isolation.check" in str(call) for call in calls)

    def test_preflight_failure_message_is_actionable(self):
        """Preflight failure messages tell user how to fix it."""
        checker = PreflightChecker(verbose=False)
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="",
            )
            
            checker.run_all_checks()
            
            # Failure message should suggest `make isolation.check`
            failure_text = " ".join(checker.failures)
            assert "isolation.check" in failure_text.lower()

    def test_preflight_passes_when_all_gates_green(self):
        """Preflight exits 0 when all Phase 18 gates pass."""
        checker = PreflightChecker(verbose=False)
        
        with patch("subprocess.run") as mock_run:
            # All checks pass
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            
            result = checker.run_all_checks()
            
            # Should pass
            assert result == 0
            assert len(checker.failures) == 0

    def test_preflight_requires_shim_only_gate_exists(self):
        """Preflight verifies ai_shims_only.py gate exists."""
        checker = PreflightChecker(verbose=False)
        
        # Check that shim gate file is verified
        assert checker.check_shim_only_gate_exists()
        
        # ai_shims_only.py should exist
        shim_file = REPO_ROOT / "xops" / "lint" / "ai_shims_only.py"
        assert shim_file.exists(), "ai_shims_only.py must exist for Phase 18 §18.3"


class TestPhase221PreflightGateExitCodes:
    """Preflight gate exit codes match CI expectations."""

    def test_preflight_zero_on_pass(self):
        """Exit code 0 on all checks passing."""
        checker = PreflightChecker(verbose=False)
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            
            result = checker.run_all_checks()
            assert result == 0

    def test_preflight_nonzero_on_failure(self):
        """Exit code non-zero on any check failing."""
        checker = PreflightChecker(verbose=False)
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Failed")
            
            result = checker.run_all_checks()
            assert result != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
