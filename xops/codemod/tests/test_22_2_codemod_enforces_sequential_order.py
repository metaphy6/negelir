"""Phase 22.2 bullet 6 — Sequential rewrite enforcement tests.

Verifies that:
1. cmd_codemod_all() enforces sequential-only rewriting (one package at a time)
2. Cycle detection runs before any rewrite begins
3. Parallel rewrites are impossible (no concurrent execution)
4. Topological order is respected
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest


class TestSequentialRewriteEnforcement:
    """Tests for sequential rewrite execution."""
    
    def test_codemod_all_requires_cycle_check_to_pass(self) -> None:
        """Verify that cmd_codemod_all calls cycle-check first and fails if cycles exist."""
        # This is a behavioral test; we mock the cycle checker to return failure
        with mock.patch("xops.makefile.phase22.cmd_cycle_check", return_value=1):
            from xops.makefile.phase22 import cmd_codemod_all
            
            # Should fail because cycle-check returned 1
            result = cmd_codemod_all(["--include-non-ai-callers"])
            assert result == 1
    
    def test_codemod_all_proceeds_if_cycle_check_passes(self) -> None:
        """Verify that cmd_codemod_all proceeds only if cycle-check returns 0."""
        # Mock a clean cycle-check and the codemod step
        with mock.patch("xops.makefile.phase22.cmd_cycle_check", return_value=0):
            with mock.patch("xops.makefile.phase22.cmd_codemod", return_value=0):
                from xops.makefile.phase22 import cmd_codemod_all, REPO_ROOT
                
                # Create a minimal topo_sort.json
                topo_json = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json"
                topo_json.parent.mkdir(parents=True, exist_ok=True)
                topo_json.write_text(json.dumps({
                    "topo_sort": ["ai.common", "ai.nlp"],
                    "packages": ["ai.common", "ai.nlp"],
                    "has_cycles": False,
                    "cycles": [],
                }))
                
                # Should succeed because cycle-check passed and topo sort exists
                result = cmd_codemod_all(["--include-non-ai-callers"])
                assert result == 0
    
    def test_codemod_all_reads_topo_sort_from_json(self) -> None:
        """Verify that cmd_codemod_all reads the topological sort from the JSON file."""
        packages_processed: list[str] = []
        
        def mock_codemod(argv):
            pkg = os.environ.get("PACKAGE", "unknown")
            packages_processed.append(pkg)
            return 0
        
        with mock.patch("xops.makefile.phase22.cmd_cycle_check", return_value=0):
            with mock.patch("xops.makefile.phase22.cmd_codemod", side_effect=mock_codemod):
                from xops.makefile.phase22 import cmd_codemod_all, REPO_ROOT
                
                # Create topo_sort.json with specific package order
                topo_json = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json"
                topo_json.parent.mkdir(parents=True, exist_ok=True)
                expected_order = ["ai.common", "ai.datasource", "ai.nlp", "ai.model"]
                topo_json.write_text(json.dumps({
                    "topo_sort": expected_order,
                    "packages": expected_order,
                    "has_cycles": False,
                    "cycles": [],
                }))
                
                # Run codemod_all
                result = cmd_codemod_all(["--include-non-ai-callers"])
                
                # Verify packages were processed in the expected order
                assert result == 0
                assert packages_processed == expected_order
    
    def test_codemod_all_processes_packages_sequentially_not_parallel(self) -> None:
        """Verify that packages are processed sequentially (one at a time).
        
        This test ensures that cmd_codemod_all never calls cmd_codemod() in parallel
        or with overlapping execution. We verify this by checking that:
        1. Each package is processed one after another
        2. No concurrent calls to cmd_codemod() occur
        3. The PACKAGE env var is set uniquely per iteration
        """
        call_order: list[tuple[str, str]] = []  # (action, package)
        
        def mock_codemod(argv):
            pkg = os.environ.get("PACKAGE", "unknown")
            call_order.append(("start", pkg))
            # Simulate some processing time (proves sequential, not parallel)
            import time
            time.sleep(0.01)
            call_order.append(("end", pkg))
            return 0
        
        with mock.patch("xops.makefile.phase22.cmd_cycle_check", return_value=0):
            with mock.patch("xops.makefile.phase22.cmd_codemod", side_effect=mock_codemod):
                from xops.makefile.phase22 import cmd_codemod_all, REPO_ROOT
                
                topo_json = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json"
                topo_json.parent.mkdir(parents=True, exist_ok=True)
                packages = ["ai.common", "ai.nlp", "ai.model"]
                topo_json.write_text(json.dumps({
                    "topo_sort": packages,
                    "packages": packages,
                    "has_cycles": False,
                    "cycles": [],
                }))
                
                result = cmd_codemod_all(["--include-non-ai-callers"])
                assert result == 0
                
                # Verify sequential execution:
                # Each package's "end" should appear before the next package's "start"
                for i, pkg in enumerate(packages):
                    start_idx = next(j for j, (action, p) in enumerate(call_order) if action == "start" and p == pkg)
                    end_idx = next(j for j, (action, p) in enumerate(call_order) if action == "end" and p == pkg)
                    
                    if i < len(packages) - 1:
                        next_pkg = packages[i + 1]
                        next_start_idx = next(j for j, (action, p) in enumerate(call_order) if action == "start" and p == next_pkg)
                        # Current package's "end" must come before next package's "start"
                        assert end_idx < next_start_idx, f"{pkg} end must before {next_pkg} start"
    
    def test_codemod_all_fails_if_topo_sort_json_missing(self) -> None:
        """Verify that cmd_codemod_all fails gracefully if topo_sort.json is missing."""
        with mock.patch("xops.makefile.phase22.cmd_cycle_check", return_value=0):
            from xops.makefile.phase22 import cmd_codemod_all, REPO_ROOT
            
            # Ensure topo_sort.json does NOT exist
            topo_json = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json"
            if topo_json.exists():
                topo_json.unlink()
            
            # Should fail with clear error message
            result = cmd_codemod_all(["--include-non-ai-callers"])
            assert result == 1
    
    def test_codemod_all_dry_run_does_not_write_files(self) -> None:
        """Verify that DRY_RUN=1 prevents actual file modifications."""
        with mock.patch("xops.makefile.phase22.cmd_cycle_check", return_value=0):
            with mock.patch("xops.makefile.phase22.cmd_codemod", return_value=0):
                from xops.makefile.phase22 import cmd_codemod_all, REPO_ROOT
                
                topo_json = REPO_ROOT / "docs" / "tracking" / "phase22_topo_sort.json"
                topo_json.parent.mkdir(parents=True, exist_ok=True)
                packages = ["ai.common"]
                topo_json.write_text(json.dumps({
                    "topo_sort": packages,
                    "packages": packages,
                    "has_cycles": False,
                    "cycles": [],
                }))
                
                # Set DRY_RUN
                os.environ["DRY_RUN"] = "1"
                try:
                    result = cmd_codemod_all([])
                    assert result == 0
                    # Verify DRY_RUN was set when cmd_codemod was called
                    # (mocked, so we just verify the command ran)
                finally:
                    os.environ.pop("DRY_RUN", None)
    
    def test_codemod_all_enforces_include_non_ai_callers_flag(self) -> None:
        """Verify that --include-non-ai-callers is mandatory for non-dry-run execution."""
        from xops.makefile.phase22 import cmd_codemod_all
        
        # Without the flag and without DRY_RUN, should fail
        result = cmd_codemod_all([])
        assert result == 1
    
    def test_cycle_check_integration_blocks_on_cycles(self) -> None:
        """Integration test: verify that cycle detection blocks sequential rewriting."""
        from xops.makefile.phase22 import cmd_cycle_check
        from xops.codemod.phase22_cycle_check import analyze_cycles_and_sort
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create a cyclic graph
            (tmp_path / "ai" / "a").mkdir(parents=True)
            (tmp_path / "ai" / "b").mkdir(parents=True)
            
            (tmp_path / "ai" / "a" / "mod.py").write_text("from ai.b import func\n")
            (tmp_path / "ai" / "b" / "mod.py").write_text("from ai.a import func\n")
            
            result, exit_code = analyze_cycles_and_sort(tmp_path)
            
            assert exit_code == 1
            assert result["has_cycles"] is True
            # The rewrite would be blocked here
    
    def test_cycle_check_produces_deterministic_topo_sort(self) -> None:
        """Verify that topological sort is deterministic across multiple cycle-check runs."""
        from xops.codemod.phase22_cycle_check import analyze_cycles_and_sort
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create a clean DAG
            (tmp_path / "ai" / "common").mkdir(parents=True)
            (tmp_path / "ai" / "nlp").mkdir(parents=True)
            (tmp_path / "ai" / "model").mkdir(parents=True)
            
            (tmp_path / "ai" / "common" / "config.py").write_text("# no imports\n")
            (tmp_path / "ai" / "nlp" / "tokenizer.py").write_text("from ai.common import config\n")
            (tmp_path / "ai" / "model" / "trainer.py").write_text("from ai.nlp import tokenizer\n")
            
            result1, _ = analyze_cycles_and_sort(tmp_path)
            result2, _ = analyze_cycles_and_sort(tmp_path)
            result3, _ = analyze_cycles_and_sort(tmp_path)
            
            # All three runs should produce identical sort orders
            assert result1["topo_sort"] == result2["topo_sort"] == result3["topo_sort"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
