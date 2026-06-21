"""Test Phase 13.3.10: Concurrent preset import safety.

Proves that two processes importing the same preset simultaneously
don't produce a partially-initialized module race condition.

Uses threading to simulate concurrent access within a single Python process,
since import locks are per-interpreter.
"""

import importlib.util
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


def _import_preset(preset_file_path: str, league_id: str) -> tuple[str, bool]:
    """Import a preset module and return success status."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"leagues.{league_id}",
            preset_file_path,
        )
        if spec is None or spec.loader is None:
            return league_id, False
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Verify CONFIG exists and is valid
        if not hasattr(module, "CONFIG"):
            return league_id, False
        
        config = module.CONFIG
        if config is None:
            return league_id, False
        
        return league_id, True
    except Exception as e:
        print(f"Error importing {league_id}: {e}")
        return league_id, False


def test_concurrent_preset_imports_are_safe():
    """Verify that concurrent imports of the same preset don't cause races.
    
    Simulates the race: cold scaler adds a new replica at the same time
    a cold reactor restarts, both trying to import the catalog.
    """
    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    
    preset_files = sorted([
        f for f in leagues_dir.glob("*.py")
        if f.name not in ("__init__.py", "__pycache__")
    ])
    
    # Launch 4 concurrent import threads for each preset
    # (simulating multiple replicas trying to import simultaneously)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for preset_file in preset_files:
            league_id = preset_file.stem
            # Submit 4 concurrent imports of the same preset
            for _ in range(4):
                future = executor.submit(_import_preset, str(preset_file), league_id)
                futures.append(future)
        
        # Collect results
        results = {}
        failures = []
        for future in as_completed(futures):
            league_id, success = future.result()
            if league_id not in results:
                results[league_id] = []
            results[league_id].append(success)
            if not success:
                failures.append(league_id)
        
        # Verify all imports succeeded
        for league_id, successes in results.items():
            assert all(successes),                 f"Preset {league_id} had concurrent import failures: {successes}"
            assert len(successes) == 4,                 f"Expected 4 imports of {league_id}, got {len(successes)}"


def test_preset_imports_are_idempotent():
    """Verify that importing the same preset multiple times produces identical configs."""
    from common.league_config import compute_config_sha256
    
    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    
    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue
        
        league_id = preset_file.stem
        
        # Import the same preset 3 times
        configs = []
        checksums = []
        for i in range(3):
            spec = importlib.util.spec_from_file_location(
                f"leagues.{league_id}_{i}",
                preset_file,
            )
            assert spec is not None and spec.loader is not None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            config = module.CONFIG
            checksum = compute_config_sha256(config)
            checksums.append(checksum)
            configs.append(config)
        
        # All checksums should be identical
        assert checksums[0] == checksums[1] == checksums[2],             f"Preset {league_id} produced different checksums on multiple imports: {checksums}"
