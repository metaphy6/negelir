"""Phase 22.13 — Verify no datasource/ folder remains at repo root."""
from pathlib import Path


def test_22_4_no_datasource_folder_at_root():
    """
    Verification: After Phase 22.4, the transitional datasource/ stub at root is gone.
    
    The stub was used to hold temporary bridge files during transition.
    After migration, all content is absorbed into root packages:
    - datasource/enrichment/ → enrichment/
    - datasource/t3_resource_manager.py → enrichment/t3_resource_manager.py
    - datasource/quarantine.py → scraper/quarantine.py
    - datasource/ folder is deleted
    """
    repo_root = Path(__file__).parent.parent.parent
    datasource_folder = repo_root / 'datasource'
    
    # The datasource stub at root should not exist after Phase 22
    # (Note: there may be a datasource/quarantine.py file at root in the pre-migration state,
    # but after Phase 22, the entire datasource/ root folder should be gone)
    assert not datasource_folder.exists(), (
        f"datasource/ folder still exists at {datasource_folder}. "
        f"Phase 22.4 should have deleted it after moving its contents to root packages."
    )
