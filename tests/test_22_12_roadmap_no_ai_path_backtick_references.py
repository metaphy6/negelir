"""Phase 22.12 — Verify ROADMAP contains no backtick-enclosed specific ai module paths."""
import re
from pathlib import Path

def test_22_12_roadmap_no_ai_path_backtick_references():
    """
    Proof test: After the ROADMAP path reference sweep, no backtick-enclosed
    ai module paths should remain in sections 17-21.
    
    This checks for specific module references like `ai/swarm/`, `ai/scraper/`,
    `ai/common/`, NOT conceptual references to the `ai/` folder itself.
    """
    roadmap = Path("docs/planning/ROADMAP.md").read_text(encoding="utf-8")
    
    # Look for backtick-enclosed ai module paths (specific packages, not generic ai/)
    # Matches patterns like `ai/swarm/`, `ai/scraper/`, `ai/common/`, etc.
    # But NOT matches like `ai/` alone (which is conceptual)
    pattern = r"`ai/(swarm|scraper|common|datasource|model|pipeline|qid|proofreader|nlp|tqu|trc|orchestrator)/"
    matches = list(re.finditer(pattern, roadmap))
    
    assert len(matches) == 0, (
        f"Found {len(matches)} backtick-enclosed ai module paths in ROADMAP. "
        f"Matches: {[m.group() for m in matches[:5]]}"
    )

if __name__ == "__main__":
    test_22_12_roadmap_no_ai_path_backtick_references()
    print("✓ No backtick-enclosed ai module paths found in ROADMAP")
