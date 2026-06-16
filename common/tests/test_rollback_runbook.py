"""Phase 18.1 §18.1 — Rollback runbook tests.

Tests verify:
- Runbook exists and contains all five steps
- Runbook documents the escape hatch procedure
- Runbook includes observability guidance
Ledger #20: rollback runbook implementation.
"""

from pathlib import Path


class TestRollbackRunbook:
    """Verify rollback runbook exists and is complete."""

    def test_rollback_runbook_exists(self) -> None:
        """Runbook must exist at docs/runbooks/phase18_rollback.md."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        assert runbook_path.exists(), f"Runbook not found at {runbook_path}"

    def test_rollback_runbook_is_markdown(self) -> None:
        """Runbook must be valid Markdown."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        content = runbook_path.read_text(encoding="utf-8")
        assert content.startswith("#"), "Runbook should start with Markdown heading"
        assert len(content) > 500, "Runbook should have substantive content"

    def test_rollback_runbook_covers_all_five_steps(self) -> None:
        """Runbook must document all five steps."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        content = runbook_path.read_text(encoding="utf-8")
        
        # Check for all five step headings
        required_steps = [
            "Step 1: Declare the Emergency",
            "Step 2: Set the Escape Hatch",
            "Step 3: Monitor the Alert Stream",
            "Step 4: Resolve the Underlying Issue",
            "Step 5: Unset the Escape Hatch",
        ]
        
        for step in required_steps:
            assert step in content, f"Runbook missing: {step}"

    def test_rollback_runbook_documents_escape_hatch(self) -> None:
        """Runbook must document the RELAX_ISOLATION_FOR_ROLLBACK escape hatch."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        content = runbook_path.read_text(encoding="utf-8")
        assert "RELAX_ISOLATION_FOR_ROLLBACK" in content
        assert "72 hours" in content or "72h" in content or "72" in content

    def test_rollback_runbook_includes_observability(self) -> None:
        """Runbook must include observability and alerting guidance."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        content = runbook_path.read_text(encoding="utf-8")
        
        # Check for observability sections
        assert "Observability" in content or "Alert" in content or "Monitor" in content
        assert "sec.alert.v1" in content or "alert" in content.lower()

    def test_rollback_runbook_includes_safety_limits(self) -> None:
        """Runbook must document limits and safeguards."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        content = runbook_path.read_text(encoding="utf-8")
        
        # Check for safeguards section
        assert "Limits" in content or "Safeguard" in content or "safe" in content.lower()
        assert "auto-unset" in content or "auto unset" in content.lower()

    def test_rollback_runbook_includes_incident_review_checklist(self) -> None:
        """Runbook must include post-incident review checklist."""
        runbook_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "runbooks"
            / "phase18_rollback.md"
        )
        content = runbook_path.read_text(encoding="utf-8")
        
        # Check for checklist
        assert "checklist" in content.lower() or "[ ]" in content
