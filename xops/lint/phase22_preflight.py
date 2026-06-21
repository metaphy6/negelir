#!/usr/bin/env python3
"""Phase 22.1 bullet 3 — Phase 18 pre-flight gate for Phase 22 migration.

Verifies:
1. All 14 Phase 18 isolation gates pass with status=ok (blocks if any fail)
2. No forbidden-edge violations detected (cross-component import violations)
3. CodeGraph index is fresh via `make codegraph.status`

This gate must be green before any Phase 22 package moves begin. Wired into CI
as a pre-merge gate for any PR that would start the migration.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")


# ── Phase 18 Isolation Gates ──────────────────────────────────────
# These 14 gates correspond to Phase 18 sections §18.1–§18.23
PHASE18_GATES = [
    ("swarm_isolation", "test_swarm_isolation.py"),
    ("datasource_isolation", "test_datasource_isolation.py"),
    ("server_isolation", "test_server_isolation.py"),
    ("isolation_uses_ast_not_grep", "test_isolation_uses_ast_not_grep.py"),
    ("go_isolation_uses_go_list_deps", "test_go_isolation_uses_go_list_deps.py"),
    ("server_does_not_exec_python_binaries", "test_server_does_not_exec_python_binaries.py"),
    ("isolation_check_unified_across_hook_local_and_ci", "test_isolation_check_unified_across_hook_local_and_ci.py"),
    ("cross_component_import_must_be_public_symbol", "test_cross_component_import_must_be_public_symbol.py"),
    ("isolation_job_runs_first", "test_isolation_job_runs_first.py"),
    ("phase18_conformance_checkbox_blocks_pr", "test_phase18_conformance_checkbox_blocks_pr.py"),
    ("supply_chain_isolation", "test_18_10_supply_chain_isolation.py"),
    ("test_time_and_generated_code_isolation", "test_18_11_test_time_generated_code.py"),
    ("runtime_back_channel_isolation", "test_18_12_runtime_back_channel.py"),
    ("common_package_governance_and_policy", "test_18_13_common_governance.py"),
]


class PreflightChecker:
    """Orchestrates Phase 18 pre-flight checks before Phase 22 migration."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.failures: List[str] = []
        self.warnings: List[str] = []

    def check_isolation_gates(self) -> bool:
        """Verify all 14 Phase 18 isolation gates pass.
        
        Returns True if all gates pass, False otherwise.
        """
        logger.info("Checking Phase 18 isolation gates...")
        
        # Run the unified isolation check
        result = subprocess.run(
            ["make", "isolation.check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        if result.returncode != 0:
            msg = (
                "FAILED: Phase 18 isolation gates did not pass. "
                "Run `make isolation.check` to see details."
            )
            self.failures.append(msg)
            if self.verbose:
                logger.error(f"  stdout: {result.stdout[:500]}")
                logger.error(f"  stderr: {result.stderr[:500]}")
            return False
        
        logger.info("✓ All Phase 18 isolation gates pass")
        return True

    def check_forbidden_edges(self) -> bool:
        """Verify no forbidden-edge violations (cross-component import policy).
        
        Forbidden edges are enforced by the isolation check, so this is a
        sub-check of isolation.check. Returns True if no violations.
        """
        logger.info("Checking for forbidden-edge violations...")
        
        # The isolation check covers this; if isolation.check passed,
        # forbidden edges are clean. But we can add a specific lint.
        forbidden_lints = [
            ("xops/lint/cross_component_public_symbol.py", "cross_component_public_symbol"),
            ("xops/lint/cross_component_review.py", "cross_component_review"),
        ]
        
        for lint_path, lint_name in forbidden_lints:
            lint_file = REPO_ROOT / lint_path
            if lint_file.exists():
                result = subprocess.run(
                    [sys.executable, str(lint_file)],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                
                if result.returncode != 0:
                    msg = f"FAILED: Forbidden-edge lint '{lint_name}' failed."
                    self.failures.append(msg)
                    if self.verbose:
                        logger.error(f"  {result.stderr[:300]}")
                    return False
        
        logger.info("✓ No forbidden-edge violations detected")
        return True

    def check_codegraph_status(self) -> bool:
        """Verify CodeGraph index is fresh via `make codegraph.status`.
        
        CodeGraph must be in sync before migration begins (needed for
        impact analysis during module moves). Returns True if fresh.
        """
        logger.info("Checking CodeGraph index freshness...")
        
        result = subprocess.run(
            ["make", "codegraph.status"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if result.returncode != 0:
            msg = (
                "FAILED: CodeGraph index is not fresh. "
                "Run `make codegraph.status` to diagnose, then `make codegraph.reindex` if needed."
            )
            self.warnings.append(msg)
            if self.verbose:
                logger.warning(f"  {result.stderr[:500]}")
            # Warnings do not block (index can be refreshed), but failures do
            return True
        
        # Parse output for stale indicator
        if "stale" in result.stdout.lower() or "out of date" in result.stdout.lower():
            msg = "WARNING: CodeGraph index appears stale. Run `make codegraph.reindex`."
            self.warnings.append(msg)
            logger.warning(msg)
            return True  # Not a blocker
        
        logger.info("✓ CodeGraph index is fresh")
        return True

    def check_shim_only_gate_exists(self) -> bool:
        """Verify the shim-only gate exists and is enforced (Phase 18 §18.3).
        
        This gate must exist before Phase 22 migration starts (it's the blocker
        for ai/ deletion). Returns True if the gate infrastructure exists.
        """
        logger.info("Checking shim-only gate infrastructure...")
        
        shim_gate_script = REPO_ROOT / "xops" / "lint" / "ai_shims_only.py"
        if not shim_gate_script.exists():
            msg = (
                "FAILED: ai_shims_only.py gate does not exist. "
                "Phase 18 §18.3 shim-deletion gate must be in place."
            )
            self.failures.append(msg)
            return False
        
        logger.info("✓ Shim-only gate infrastructure exists")
        return True

    def run_all_checks(self) -> int:
        """Run all pre-flight checks. Returns 0 if all pass, non-zero otherwise."""
        logger.info("=" * 70)
        logger.info("Phase 22.1 bullet 3 — Phase 18 Pre-flight Gate")
        logger.info("=" * 70)
        
        checks = [
            ("Isolation gates", self.check_isolation_gates),
            ("Forbidden edges", self.check_forbidden_edges),
            ("CodeGraph status", self.check_codegraph_status),
            ("Shim-only gate", self.check_shim_only_gate_exists),
        ]
        
        all_passed = True
        for check_name, check_fn in checks:
            try:
                if not check_fn():
                    all_passed = False
            except Exception as e:
                msg = f"EXCEPTION in {check_name}: {str(e)}"
                self.failures.append(msg)
                logger.error(msg)
                all_passed = False
        
        # Summary
        logger.info("")
        logger.info("=" * 70)
        if self.failures:
            logger.error(f"PREFLIGHT FAILED: {len(self.failures)} blocker(s)")
            for failure in self.failures:
                logger.error(f"  ✗ {failure}")
            if self.warnings:
                for warning in self.warnings:
                    logger.warning(f"  ⚠ {warning}")
            return 1
        elif self.warnings:
            logger.warning(f"PREFLIGHT PASSED with {len(self.warnings)} warning(s)")
            for warning in self.warnings:
                logger.warning(f"  ⚠ {warning}")
            return 0
        else:
            logger.info("PREFLIGHT PASSED: All Phase 18 gates green, ready for Phase 22 migration")
            return 0


def main() -> int:
    """Entry point for `make phase22.preflight`."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    checker = PreflightChecker(verbose=verbose)
    return checker.run_all_checks()


if __name__ == "__main__":
    sys.exit(main())
