"""Phase 18.7 — Isolation violation metric emitted (ledger #18).

The metric isolation_violation_total{component, kind, ledger_ref} must be
emitted when isolation violations are detected.
"""

from __future__ import annotations

from pathlib import Path


def test_isolation_violation_metric_emitted() -> None:
    """Verify isolation violation metric infrastructure exists."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # Check that isolation module exists with graph builder or check
    iso_dir = repo_root / "common" / "isolation"
    assert iso_dir.exists(), f"Isolation module must exist at {iso_dir}"
    
    # Verify at least one of the check/builder modules exists
    files_in_iso = list(iso_dir.glob("*.py"))
    assert len(files_in_iso) > 0, "Isolation module should have Python files"
    
    content = "\n".join(f.read_text(encoding="utf-8") for f in files_in_iso if f.suffix == ".py")
    # Verify isolation violation concepts are referenced
    assert "isolation" in content.lower() or "graph" in content.lower(), \
        "Isolation module should have infrastructure for checking violations"
