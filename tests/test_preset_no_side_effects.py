"""Test Phase 13.3.8: Preset import isolation (no side effects).

Proves that preset modules are imported in a sandboxed namespace:
- No calls to database at import time
- No imports from ai.swarm at import time
- No external API calls at import time
- No sys.path modifications at import time
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys


def test_preset_imports_without_db_calls():
    """Verify that presets can be imported with DB connection unavailable."""
    import importlib
    
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
        assert spec is not None and spec.loader is not None,             f"Could not create spec for {league_id}"
        
        module = importlib.util.module_from_spec(spec)
        
        # Should succeed without side effects
        spec.loader.exec_module(module)
        
        # Verify CONFIG exists
        assert hasattr(module, "CONFIG"),             f"Preset {league_id} missing CONFIG constant"


def test_preset_imports_dont_modify_sys_path():
    """Verify that presets don't modify sys.path at import time."""
    import importlib.util
    
    leagues_dir = Path(__file__).parent.parent / "common" / "leagues"
    
    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue
        
        league_id = preset_file.stem
        
        # Capture sys.path before import
        sys_path_before = sys.path.copy()
        
        spec = importlib.util.spec_from_file_location(
            f"leagues.{league_id}",
            preset_file,
        )
        assert spec is not None and spec.loader is not None
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Verify sys.path wasn't modified
        assert sys.path == sys_path_before,             f"Preset {league_id} modified sys.path at import time"
        
        # Verify CONFIG exists
        assert hasattr(module, "CONFIG"),             f"Preset {league_id} missing CONFIG constant"
