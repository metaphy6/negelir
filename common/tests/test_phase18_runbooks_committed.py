"""Phase 18.8 — phase18_rollback.md and phase18_layout_freeze.md must exist with drill checklists."""

from pathlib import Path


def test_phase18_rollback_runbook_exists() -> None:
    """phase18_rollback.md must exist."""
    repo_root = Path(__file__).resolve().parents[2]
    runbook = repo_root / "docs" / "runbooks" / "phase18_rollback.md"
    
    assert runbook.exists(), "phase18_rollback.md not found"
    
    content = runbook.read_text(encoding="utf-8")
    assert "Quarterly Drill Checklist" in content or "quarterly drill" in content.lower()
    assert "[ ]" in content, "no checklist items found"


def test_phase18_layout_freeze_runbook_exists() -> None:
    """phase18_layout_freeze.md must exist."""
    repo_root = Path(__file__).resolve().parents[2]
    runbook = repo_root / "docs" / "runbooks" / "phase18_layout_freeze.md"
    
    assert runbook.exists(), "phase18_layout_freeze.md not found"
    
    content = runbook.read_text(encoding="utf-8")
    assert "Quarterly" in content, "no quarterly reference"
    assert "[ ]" in content, "no checklist items found"


def test_runbooks_have_drill_procedures() -> None:
    """Both runbooks must include quarterly drill procedures."""
    repo_root = Path(__file__).resolve().parents[2]
    
    rollback = (repo_root / "docs" / "runbooks" / "phase18_rollback.md").read_text()
    freeze = (repo_root / "docs" / "runbooks" / "phase18_layout_freeze.md").read_text()
    
    assert "Quarterly" in rollback or "quarterly" in rollback
    assert "Quarterly" in freeze or "quarterly" in freeze
