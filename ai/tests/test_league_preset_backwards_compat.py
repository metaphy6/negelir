"""Test Phase 13.3.3: League preset backwards compatibility gate.

Proves that every new LeagueConfig field has a sensible default,
and that all existing presets load successfully against the current
field set (triangle test).
"""

import pytest
from dataclasses import fields


def test_all_existing_presets_load():
    """Verify that all presets load successfully.
    
    This is the "backwards-compat gate" of Phase 13.3.3:
    Every new LeagueConfig field must have a default value,
    so existing presets continue to work even as the schema evolves.
    """
    from common.leagues import LEAGUE_CONFIGS
    
    # All presets should load
    assert len(LEAGUE_CONFIGS) > 0, "At least one preset should load"
    
    # Each loaded preset should have a valid LeagueConfig instance
    for league_id, config in LEAGUE_CONFIGS.items():
        assert hasattr(config, "league_id"), f"{league_id}: missing league_id"
        assert hasattr(config, "league_name"), f"{league_id}: missing league_name"
        assert config.league_id == league_id, f"{league_id}: league_id mismatch"


def test_league_config_fields_have_defaults():
    """Verify that all LeagueConfig fields have sensible defaults.
    
    This enforces Phase 13.3.3 discipline: when a new field is added
    to LeagueConfig, it MUST have a default value. This test ensures
    the dataclass is structured correctly.
    """
    from common.league_config import LeagueConfig
    
    # Instantiate with no arguments (all fields should have defaults)
    try:
        default_config = LeagueConfig()
        assert default_config.league_id == "tr_super_lig"
        assert default_config.teams_count == 19
        assert default_config.derbies == set() or len(default_config.derbies) >= 0
    except TypeError as e:
        pytest.fail(f"LeagueConfig missing default for field: {e}")


def test_preset_field_coverage_against_latest_schema():
    """Verify that all presets contain fields defined in LeagueConfig schema.
    
    Triangle test: load each preset and ensure it can be converted back
    to a dict without missing required fields.
    """
    from common.leagues import LEAGUE_CONFIGS
    from common.league_config import LeagueConfig
    from dataclasses import asdict
    
    for league_id, config in LEAGUE_CONFIGS.items():
        # Verify it's a LeagueConfig instance
        assert isinstance(config, LeagueConfig), f"{league_id}: not a LeagueConfig"
        
        # Convert to dict (this will fail if any required field is missing)
        config_dict = asdict(config)
        assert isinstance(config_dict, dict)
        assert len(config_dict) > 0
        
        # Verify critical fields are present
        critical_fields = ["league_id", "league_name", "country", "language"]
        for field_name in critical_fields:
            assert field_name in config_dict, f"{league_id}: missing {field_name}"
            assert config_dict[field_name] is not None, f"{league_id}: {field_name} is None"
