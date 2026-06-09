"""Test Phase 13.3.2: League preset error isolation.

Proves that a broken preset does not prevent the aggregator from
loading all other presets.
"""

import pytest


def test_one_bad_preset_does_not_break_others():
    """Verify that a syntax-error preset does not break the aggregator.
    
    This tests Phase 13.3.2 discipline: the aggregator wraps each
    import in try/except and skips on failure, never cascading the
    error to other presets.
    """
    from common.leagues import load_league_configs, get_league_config
    
    # Force reload to pick up the broken preset we added
    import sys
    if "common.leagues" in sys.modules:
        del sys.modules["common.leagues"]
    
    # Load all presets (including the broken one)
    configs = load_league_configs()
    
    # Verify that TR Super Lig loads successfully
    assert "tr_super_lig" in configs, "TR Super Lig should load despite broken preset"
    assert configs["tr_super_lig"].league_name == "Turkish Süper Lig"
    
    # Verify that the broken preset is skipped
    assert "broken_league_syntax_error" not in configs, "Broken preset should be skipped"
    
    # Verify that get_league_config also works
    tr_config = get_league_config("tr_super_lig")
    assert tr_config is not None
    assert tr_config.league_id == "tr_super_lig"
    
    # Verify that requesting a non-existent league returns None
    assert get_league_config("nonexistent_league") is None


def test_all_loadable_presets_have_config_constant():
    """Verify that all successfully loaded presets expose CONFIG."""
    from common.leagues import LEAGUE_CONFIGS
    
    # All loaded presets should have CONFIG_SHA256 eventually (Phase 13.21)
    # For now, just verify they are LeagueConfig instances
    for league_id, config in LEAGUE_CONFIGS.items():
        assert hasattr(config, "league_id"), f"{league_id} preset missing league_id"
        assert hasattr(config, "league_name"), f"{league_id} preset missing league_name"
        assert config.league_id == league_id, f"league_id mismatch: {config.league_id} != {league_id}"


def test_league_configs_module_constant():
    """Verify that LEAGUE_CONFIGS is accessible as a module constant."""
    from common.leagues import LEAGUE_CONFIGS
    
    assert isinstance(LEAGUE_CONFIGS, dict), "LEAGUE_CONFIGS should be a dict"
    assert len(LEAGUE_CONFIGS) > 0, "LEAGUE_CONFIGS should not be empty"
    assert "tr_super_lig" in LEAGUE_CONFIGS, "TR Super Lig should be in LEAGUE_CONFIGS"
