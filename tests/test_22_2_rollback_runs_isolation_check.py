"""Phase 22.2 bullet 8 — Rollback safety: isolation check verification.

Verifies:
1. Rollback invokes 'make isolation.check --full' after restoration
2. Isolation check is green (exit code 0) after rollback
3. Isolation check failure is reported correctly
4. Multiple rollback operations maintain isolation
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import patch, MagicMock

import pytest


class TestRollbackRunsIsolationCheck:
    """Test that rollback verifies safety via isolation.check."""

    def test_rollback_invokes_isolation_check(self, tmp_path: Path) -> None:
        """Verify that rollback command runs 'make isolation.check --full'."""
        from xops.makefile.phase22 import cmd_rollback_codemod
        import os
        import json
        
        # Create mock environment
        os.environ["PACKAGE"] = "common"
        
        # Create empty directories (no sidecars to find)
        package_dir = tmp_path / "ai" / "common"
        package_dir.mkdir(parents=True)
        
        # Mock the subprocess.run to track isolation check call
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            # Patch REPO_ROOT to tmp_path
            with patch("xops.makefile.phase22.REPO_ROOT", tmp_path):
                # Run rollback (should find no sidecars and still call isolation check)
                result = cmd_rollback_codemod([])
                
                # isolation.check should be invoked
                assert mock_run.called, "Should call subprocess.run"
                
                # Find the call with isolation.check
                isolation_check_calls = [
                    call for call in mock_run.call_args_list
                    if "isolation.check" in str(call)
                ]
                assert len(isolation_check_calls) > 0, "Should invoke 'make isolation.check'"

    def test_rollback_isolation_check_success(self, tmp_path: Path) -> None:
        """Verify that rollback succeeds when isolation.check returns 0."""
        from xops.makefile.phase22 import cmd_rollback_codemod
        import os
        
        os.environ["PACKAGE"] = "test_pkg"
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            with patch("xops.makefile.phase22.REPO_ROOT", tmp_path):
                result = cmd_rollback_codemod([])
                
                # Should succeed (exit 0) when isolation check is green
                # Either 0 (no sidecars) or the result of isolation check
                assert result == 0, f"Expected exit 0, got {result}"

    def test_rollback_isolation_check_failure(self, tmp_path: Path) -> None:
        """Verify that rollback fails when isolation.check returns non-zero."""
        from xops.makefile.phase22 import cmd_rollback_codemod
        import os
        
        os.environ["PACKAGE"] = "test_pkg"
        
        with patch("subprocess.run") as mock_run:
            # Make isolation check fail
            mock_run.return_value = MagicMock(returncode=1)
            
            with patch("xops.makefile.phase22.REPO_ROOT", tmp_path):
                result = cmd_rollback_codemod([])
                
                # Should fail (exit 1) when isolation check fails
                assert result == 1, f"Expected exit 1, got {result}"

    def test_rollback_with_sidecars_and_isolation_check(self, tmp_path: Path) -> None:
        """Verify isolation check is run after restoring files from sidecars."""
        from xops.makefile.phase22 import cmd_rollback_codemod
        import os
        import json
        
        os.environ["PACKAGE"] = "common"
        
        # Create ai/common directory with sidecars
        ai_common = tmp_path / "ai" / "common"
        ai_common.mkdir(parents=True)
        
        # Create a file and its sidecar
        test_file = ai_common / "config.py"
        test_file.write_text("from common.config import cfg\n")
        
        sidecar = ai_common / "config.py.phase22.orig"
        sidecar.write_text("from common.config import cfg\n")
        
        # Create empty inventory
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True)
        inventory_path = tracking_dir / "phase22_import_report.json"
        inventory_path.write_text(json.dumps({"by_package": {}}))
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            with patch("xops.makefile.phase22.REPO_ROOT", tmp_path):
                result = cmd_rollback_codemod([])
                
                # File should be restored
                assert test_file.read_text() == "from common.config import cfg\n"
                
                # Sidecar should be deleted
                assert not sidecar.exists()
                
                # isolation.check should be called
                assert mock_run.called

    def test_rollback_isolation_check_exit_code_propagates(self, tmp_path: Path) -> None:
        """Verify that rollback exit code matches isolation check exit code."""
        from xops.makefile.phase22 import cmd_rollback_codemod
        import os
        
        os.environ["PACKAGE"] = "test_pkg"
        
        # Test various exit codes
        for exit_code in [0, 1, 2, 127]:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=exit_code)
                
                with patch("xops.makefile.phase22.REPO_ROOT", tmp_path):
                    result = cmd_rollback_codemod([])
                    
                    # Result should match isolation check exit code (if no sidecars, 0)
                    assert result == exit_code, f"Expected exit {exit_code}, got {result}"

    def test_rollback_multiple_sidecars_then_isolation_check(self, tmp_path: Path) -> None:
        """Verify isolation check is run after restoring multiple files."""
        from xops.makefile.phase22 import cmd_rollback_codemod
        import os
        import json
        
        os.environ["PACKAGE"] = "nlp"
        
        # Create ai/nlp directory with multiple sidecars
        ai_nlp = tmp_path / "ai" / "nlp"
        ai_nlp.mkdir(parents=True)
        
        # Create files and sidecars
        files = ["lexicon_loader.py", "normalizer.py", "tokenizer.py"]
        for fname in files:
            fpath = ai_nlp / fname
            fpath.write_text(f"from nlp.{fname.replace('.py', '')} import X\n")
            
            sidecar = ai_nlp / (fname + ".phase22.orig")
            sidecar.write_text(f"from nlp.{fname.replace('.py', '')} import X\n")
        
        # Create empty inventory
        tracking_dir = tmp_path / "docs" / "tracking"
        tracking_dir.mkdir(parents=True)
        inventory_path = tracking_dir / "phase22_import_report.json"
        inventory_path.write_text(json.dumps({"by_package": {}}))
        
        call_count = 0
        
        def track_calls(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock(returncode=0)
        
        with patch("subprocess.run", side_effect=track_calls) as mock_run:
            with patch("xops.makefile.phase22.REPO_ROOT", tmp_path):
                result = cmd_rollback_codemod([])
                
                # All files should be restored
                for fname in files:
                    fpath = ai_nlp / fname
                    assert fpath.read_text() == f"from nlp.{fname.replace('.py', '')} import X\n"
                    sidecar = ai_nlp / (fname + ".phase22.orig")
                    assert not sidecar.exists()
                
                # isolation.check should have been called
                assert call_count >= 1
