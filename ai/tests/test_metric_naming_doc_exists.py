"""Phase 18.7 — Metric naming doc exists (ledger #18).

The metric naming convention must be documented in common/observability/metric_naming.md.
"""

from __future__ import annotations

from pathlib import Path


def test_metric_naming_doc_exists() -> None:
    """Verify metric naming documentation exists."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # The doc must exist
    doc_path = repo_root / "common" / "observability" / "metric_naming.md"
    assert doc_path.exists(), \
        f"Metric naming documentation must exist at {doc_path}"
    
    # Read and verify content
    content = doc_path.read_text(encoding="utf-8")
    assert len(content) > 100, "Metric naming doc should contain substantive content"
    
    # Verify key concepts are documented
    required_terms = ["component", "subsystem", "verb", "unit"]
    for term in required_terms:
        assert term.lower() in content.lower(), \
            f"Metric naming doc must document '{term}'"
