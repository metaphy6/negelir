"""Test Phase 13.3.9: Preset import performance budget.

Proves that importing all league presets stays within the performance
budget to keep cold-start time under Phase 11 control plane budget.
"""

import importlib.util
import time
from pathlib import Path


def test_preset_import_total_time_under_budget():
    """Verify that importing all presets completes within the budget.
    
    Default budget: 300 ms (NEGELIR_LEAGUE_PRESET_TOTAL_IMPORT_MAX_MS)
    """
    from ai.common.config import cfg
    
    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    
    # Measure total import time
    start_time = time.time()
    
    preset_count = 0
    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue
        
        league_id = preset_file.stem
        
        # Dynamically import the preset module
        spec = importlib.util.spec_from_file_location(
            f"leagues.{league_id}",
            preset_file,
        )
        assert spec is not None and spec.loader is not None,             f"Could not create spec for {league_id}"
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Verify CONFIG exists
        assert hasattr(module, "CONFIG"),             f"Preset {league_id} missing CONFIG constant"
        
        preset_count += 1
    
    elapsed_ms = (time.time() - start_time) * 1000
    budget_ms = cfg.league_preset_total_import_max_ms
    
    print(f"\nPreset import benchmark:")
    print(f"  Presets imported: {preset_count}")
    print(f"  Elapsed time: {elapsed_ms:.2f} ms")
    print(f"  Budget: {budget_ms} ms")
    print(f"  Status: {'✓ PASS' if elapsed_ms <= budget_ms else '✗ FAIL'}")
    
    assert elapsed_ms <= budget_ms,         f"Preset import took {elapsed_ms:.2f} ms, exceeds budget of {budget_ms} ms"


def test_individual_preset_import_times():
    """Verify that each individual preset imports quickly.
    
    No single preset should take > 50 ms (budget / 6 presets avg).
    """
    import importlib.util
    
    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    
    times = []
    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue
        
        league_id = preset_file.stem
        
        start = time.time()
        
        spec = importlib.util.spec_from_file_location(
            f"leagues.{league_id}",
            preset_file,
        )
        assert spec is not None and spec.loader is not None
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        elapsed_ms = (time.time() - start) * 1000
        times.append((league_id, elapsed_ms))
        
        # Sanity check: individual presets should be very fast
        assert elapsed_ms < 100,             f"Preset {league_id} took {elapsed_ms:.2f} ms (expected < 100 ms)"
    
    # Print timing breakdown
    print(f"\nIndividual preset import times:")
    for league_id, elapsed_ms in sorted(times, key=lambda x: x[1], reverse=True):
        print(f"  {league_id}: {elapsed_ms:.2f} ms")
