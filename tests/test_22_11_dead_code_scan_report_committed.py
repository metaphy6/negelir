"""Phase 22.11 — Proof test for dead-code scan report commitment.

Verifies that the Phase 22.1 pre-flight vulture scan output exists
and contains the expected structure.
"""
from pathlib import Path
import re


def test_22_11_dead_code_scan_report_committed() -> None:
    """Phase 22.11 bullet 1: Verify vulture scan report file exists."""
    report_path = Path("docs/tracking/phase22_dead_code_candidates.md")
    assert report_path.exists(), (
        f"Dead-code scan report missing: {report_path}. "
        "Run `make phase22.dead-code` to generate."
    )
    
    content = report_path.read_text(encoding="utf-8")
    
    # Verify required sections
    assert "Scan Status:" in content, "Missing 'Scan Status' section"
    assert "Summary" in content, "Missing 'Summary' section"
    assert "Confidence Threshold:" in content, "Missing threshold documentation"
    
    # Verify it documents the scan result (either candidates or clean)
    assert (
        "No confirmed dead symbols" in content or 
        "candidates" in content.lower()
    ), "Report must document scan results clearly"


def test_22_11_no_confirmed_dead_symbols_at_root() -> None:
    """Phase 22.11 bullet 1: Verify scan found no blocking dead symbols.
    
    After migration, all root packages maintain active call sites.
    No symbols at 80%+ confidence should be marked for removal.
    """
    report_path = Path("docs/tracking/phase22_dead_code_candidates.md")
    content = report_path.read_text(encoding="utf-8")
    
    # The report should indicate either:
    # 1. No symbols found needing removal, OR
    # 2. A list of symbols reviewed and their status (removed/whitelisted)
    
    # For now, verify the post-migration state is clean
    assert "No confirmed dead symbols requiring removal" in content, (
        "Expected scan to find no blocking dead code after migration. "
        "See docs/tracking/phase22_dead_code_candidates.md for details."
    )
