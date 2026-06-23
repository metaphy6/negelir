"""Phase 22.4 / 22.8 — Regression check: datasource/ folder must not exist at repo root."""

from pathlib import Path


def test_no_datasource_folder_at_root():
    """Verify datasource/ does not exist at repo root (Phase 22.2 § 22.4 must have moved it)."""
    repo_root = Path(__file__).parent.parent
    datasource_at_root = repo_root / "datasource"
    
    assert not datasource_at_root.exists(), (
        "datasource/ should not exist at repo root; it should be under ai/ as ai/datasource/ "
        "until Phase 22 migration is complete"
    )


def test_ai_datasource_might_exist():
    """Verify ai/datasource/ exists (or will exist once Phase 22 migration starts)."""
    repo_root = Path(__file__).parent.parent
    ai_datasource = repo_root / "ai" / "datasource"
    
    # During Phase 22, datasource code lives in ai/datasource/
    # After the migration, the module moves and ai/ folder is deleted
    # This test documents the expected state during Phase 22: datasource NOT at root
    if ai_datasource.exists():
        # If ai/datasource exists, that's fine - we're in the transition phase
        assert ai_datasource.is_dir(), "ai/datasource should be a directory"
    # If it doesn't exist, we might be post-migration, but at minimum
    # datasource should NOT be at root


if __name__ == "__main__":
    test_no_datasource_folder_at_root()
    print("✅ test_no_datasource_folder_at_root passed")
    
    test_ai_datasource_might_exist()
    print("✅ test_ai_datasource_might_exist passed")
    
    print("\n✅ All datasource folder tests passed!")
