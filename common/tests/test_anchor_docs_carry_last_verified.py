"""Phase 18.8 — Anchor docs carry last_verified_against_code front-matter.

Proof test: Verify each anchor doc has the required front-matter field.
"""

from __future__ import annotations

import re
from pathlib import Path


def test_anchor_docs_carry_last_verified_front_matter() -> None:
    """Every anchor doc must have last_verified_against_code front-matter."""
    repo_root = Path(__file__).resolve().parents[2]
    
    anchor_docs = [
        "docs/design/COMPONENT_LAYOUT.md",
        "docs/design/DATA_PIPELINE.md",
        "docs/design/EMITTER.md",
        "docs/design/SWARM.md",
        "docs/design/SCRAPER_PATCHER.md",
        "docs/design/SECURITY.md",
    ]
    
    missing = []
    
    for doc_path_str in anchor_docs:
        doc_path = repo_root / doc_path_str
        assert doc_path.exists(), f"{doc_path_str} not found"
        
        content = doc_path.read_text(encoding="utf-8")
        
        # Check for last_verified_against_code in front-matter comment
        if not re.search(r"last_verified_against_code:\s*\d{4}-\d{2}-\d{2}", content):
            missing.append(doc_path_str)
    
    assert not missing, f"Anchor docs missing last_verified_against_code: {missing}"


def test_anchor_doc_dates_are_valid_iso() -> None:
    """Dates in anchor docs must be valid ISO format (YYYY-MM-DD)."""
    repo_root = Path(__file__).resolve().parents[2]
    
    anchor_docs = [
        "docs/design/COMPONENT_LAYOUT.md",
        "docs/design/DATA_PIPELINE.md",
        "docs/design/EMITTER.md",
        "docs/design/SWARM.md",
        "docs/design/SCRAPER_PATCHER.md",
        "docs/design/SECURITY.md",
    ]
    
    invalid = []
    
    for doc_path_str in anchor_docs:
        doc_path = repo_root / doc_path_str
        content = doc_path.read_text(encoding="utf-8")
        
        match = re.search(r"last_verified_against_code:\s*(\d{4}-\d{2}-\d{2})", content)
        if match:
            date_str = match.group(1)
            # Validate ISO format
            try:
                import datetime
                datetime.date.fromisoformat(date_str)
            except ValueError:
                invalid.append((doc_path_str, date_str))
    
    assert not invalid, f"Invalid ISO dates: {invalid}"
