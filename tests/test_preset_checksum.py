"""Test Phase 13.3.7: Preset checksum validation.

Proves that each preset module exposes a CONFIG_SHA256 that matches
the computed checksum over canonical dataclasses.asdict().

Used by Phase 13.21 audit log to detect silent edits to presets.
"""

import importlib.util
from pathlib import Path


def test_preset_checksum_matches_for_tr_super_lig():
    """Verify that TR Super Lig CONFIG_SHA256 matches computed checksum.
    
    Note: CONFIG_SHA256 is a frozen constant in the preset file. This test
    verifies that the constant matches what compute_config_sha256() produces
    for the CONFIG object. If this test fails after editing CONFIG, the
    CONFIG_SHA256 constant must be updated to the newly computed value.
    """
    from common.league_config import compute_config_sha256
    from common.leagues.tr_super_lig import CONFIG, CONFIG_SHA256

    computed_sha = compute_config_sha256(CONFIG)
    if CONFIG_SHA256 != computed_sha:
        print(f"\n⚠️  CONFIG_SHA256 mismatch in tr_super_lig.py")
        print(f"  Declared: {CONFIG_SHA256}")
        print(f"  Computed: {computed_sha}")
        print(f"  Update CONFIG_SHA256 = \"{computed_sha}\" in tr_super_lig.py")
    
    assert (
        CONFIG_SHA256 == computed_sha
    ), f"CONFIG_SHA256 mismatch: declared={CONFIG_SHA256}, computed={computed_sha}"


def test_all_presets_have_config_sha256():
    """Verify that all preset modules expose CONFIG_SHA256."""
    from common.league_config import compute_config_sha256
    
    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    
    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue
        
        league_id = preset_file.stem
        
        # Dynamically import the preset module
        spec = importlib.util.spec_from_file_location(
            f"leagues.{league_id}",
            preset_file,
        )
        assert spec is not None and spec.loader is not None, \
            f"Could not create spec for {league_id}"
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Verify CONFIG exists
        assert hasattr(module, "CONFIG"), \
            f"Preset {league_id} missing CONFIG constant"
        
        # Verify CONFIG_SHA256 exists
        assert hasattr(module, "CONFIG_SHA256"), \
            f"Preset {league_id} missing CONFIG_SHA256 constant"
        
        # Verify checksum matches
        config = module.CONFIG
        declared_sha = module.CONFIG_SHA256
        computed_sha = compute_config_sha256(config)
        
        assert (
            declared_sha == computed_sha
        ), f"Preset {league_id}: CONFIG_SHA256 mismatch: " \
           f"declared={declared_sha}, computed={computed_sha}"


def test_config_sha256_is_deterministic():
    """Verify that CONFIG_SHA256 is computed deterministically.
    
    Loading the same CONFIG multiple times and computing its hash
    must always produce the same result (no dict-ordering drift,
    float precision, etc.).
    """
    from common.league_config import compute_config_sha256
    from common.leagues.tr_super_lig import CONFIG
    
    hashes = [compute_config_sha256(CONFIG) for _ in range(5)]
    assert len(set(hashes)) == 1, \
        f"CONFIG_SHA256 is not deterministic: {hashes}"


def test_config_sha256_changes_on_field_edit():
    """Verify that altering a CONFIG field changes the checksum.
    
    This is a negative test: modifying a config value should produce
    a different hash (proving the checksum is not a fixed constant).
    """
    from dataclasses import replace
    from common.league_config import compute_config_sha256
    from common.leagues.tr_super_lig import CONFIG
    
    original_sha = compute_config_sha256(CONFIG)
    
    # Create a modified config
    modified_config = replace(CONFIG, elo_initial=1600.0)
    modified_sha = compute_config_sha256(modified_config)
    
    assert original_sha != modified_sha, \
        f"CONFIG_SHA256 did not change after field edit: {original_sha}"
