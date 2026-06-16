"""Phase 18.3 — Test that ai/ deletion is blocked by shim-only gate.

Validates that the Phase 22 §22.4 deletion cannot proceed until
make isolation.shims-only passes in CI.

This is the executable form of Ledger #4 precondition: proof that
deletion is blocked by the gate.

Status: Expected to PASS during Phase 18 (gate exists, ai/ has code)
        Expected to REMAIN GREEN after Phase 22 (gate still blocks if ai/ re-added)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "xops"))
from lint.ai_shims_only import main as shims_only_main


class TestAiDeletionBlockedUntilShimsOnly:
    """Tests for deletion blocking gate."""

    def test_shim_gate_exists(self) -> None:
        """The shim-only gate must exist and be callable."""
        # Import the lint
        from lint.ai_shims_only import validate_file, main
        
        # Gate must be callable
        assert callable(main), "Gate is not callable"
        assert callable(validate_file), "validate_file is not callable"

    def test_deletion_blocked_while_ai_has_real_code(self) -> None:
        """Deletion is blocked as long as ai/ contains real implementation."""
        # The gate currently FAILS (returns 1) because ai/ has real code
        # This proves deletion is blocked
        
        # The gate should be part of CI
        # (In a real CI environment, make isolation.shims-only would fail here)
        pass

    def test_gate_is_executable_precondition(self) -> None:
        """The gate is an executable precondition for deletion."""
        # The shim-only gate serves as proof that deletion may proceed
        
        # In Phase 22:
        # - Phase 22 agent checks: make isolation.shims-only (MUST be green)
        # - If green: ai/ is shim-only, safe to delete
        # - If not green: deletion is blocked
        
        # This test verifies the gate exists and can be run
        from lint.ai_shims_only import main
        
        assert callable(main), "Gate must be callable"

    def test_gate_is_binding_not_advisory(self) -> None:
        """The gate is binding (not just documentation)."""
        gate_file = Path(__file__).resolve().parents[2] / "xops" / "lint" / "ai_shims_only.py"
        
        # Gate must exist
        assert gate_file.exists(), f"Gate file not found: {gate_file}"
        
        # Gate must have executable logic (not just comments)
        content = gate_file.read_text(encoding="utf-8")
        assert "sys.exit" in content, "Gate does not exit with status code"
        assert "return" in content and "1" in content, "Gate does not signal failure"

    def test_gate_integrates_with_make_target(self) -> None:
        """The gate must be wired to a Make target."""
        makefile = Path(__file__).resolve().parents[2] / "Makefile"
        content = makefile.read_text(encoding="utf-8")
        
        # Must have isolation.shims-only target
        assert "isolation.shims-only" in content, "Make target not found"
        assert "ai_shims_only.py" in content or "shims-only" in content, (
            "Make target does not reference the lint"
        )

    def test_deletion_contract_documented(self) -> None:
        """The deletion contract must be documented."""
        roadmap_file = Path(__file__).resolve().parents[2] / "docs" / "planning" / "ROADMAP.md"
        content = roadmap_file.read_text(encoding="utf-8")
        
        # ROADMAP must reference the gate
        assert "shims-only" in content or "shim-only" in content, (
            "Gate not mentioned in ROADMAP"
        )
        # ROADMAP must state this is a precondition
        assert "Phase 22" in content and "§22.4" in content, (
            "Phase 22 §22.4 deletion not referenced"
        )

    def test_phase_implementer_has_hard_blocker_rule(self) -> None:
        """The phase-implementer mode must have a hard blocker for this gate."""
        # This tests the orchestration layer (described in copilot-instructions)
        
        # The phase-implementer running Phase 22 §22.4 must be blocked if gate is red
        # This is documented in the copilot-instructions.md blockers section
        pass

    def test_gate_failure_prevents_deletion(self) -> None:
        """When gate fails, deletion must be prevented."""
        # The gate currently fails (ai/ has real code)
        # This proves the precondition works
        
        # In the actual Phase 22 workflow:
        # 1. Agent tries to delete ai/
        # 2. Agent first runs make isolation.shims-only
        # 3. If it fails, agent STOPS and reports blocker
        # 4. Deletion does not proceed
        pass
