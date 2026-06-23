"""Phase 22.13 — Verify ai/ tree is completely gone."""
from pathlib import Path


def test_ai_tree_gone():
    """
    Verification: The ai/ folder at repo root does not exist.
    
    After Phase 22 migration, all code has been moved from ai/ to root packages
    (datasource/, swarm/, common/). The ai/ folder itself should be deleted.
    """
    repo_root = Path(__file__).parent.parent.parent
    ai_folder = repo_root / 'ai'
    
    assert not ai_folder.exists(), (
        f"ai/ folder still exists at {ai_folder}. "
        f"Phase 22 migration should have deleted it completely."
    )
