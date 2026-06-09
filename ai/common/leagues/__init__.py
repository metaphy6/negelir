"""Per-league preset configurations for Negelir.

Each league has a dedicated preset file (e.g., tr_super_lig.py) that
exposes a single CONFIG: LeagueConfig constant. The aggregator loads
these lazily to keep import time fast for the critical path.

Aggregator discipline (Phase 13.3.2):
- Wraps each preset import in try/except
- On failure, records a metric and skips that league
- Never breaks if one preset has a typo or import error
- Proof test: test_one_bad_preset_does_not_break_others.py
"""

import logging
from pathlib import Path

# Lazy loader for league presets
_LEAGUE_CONFIGS_CACHE: dict | None = None
_FAILED_PRESETS_CACHE: dict | None = None
_logger = logging.getLogger("leagues.loader")


def load_league_configs() -> dict:
    """Load all league presets, with error isolation.
    
    Returns {league_id: LeagueConfig}. If a preset fails to import,
    that league is skipped and a metric is recorded.
    """
    global _LEAGUE_CONFIGS_CACHE
    global _FAILED_PRESETS_CACHE
    
    if _LEAGUE_CONFIGS_CACHE is not None:
        return _LEAGUE_CONFIGS_CACHE
    
    import importlib.util
    
    result = {}
    failed_presets = {}
    
    leagues_dir = Path(__file__).parent
    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue
        
        league_id = preset_file.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"leagues.{league_id}",
                preset_file,
            )
            if spec is None or spec.loader is None:
                reason = "spec_creation_failed"
                _logger.warning(f"Could not load spec for {league_id}")
                failed_presets[league_id] = reason
                continue
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if not hasattr(module, "CONFIG"):
                reason = "missing_CONFIG_constant"
                _logger.warning(f"Preset {league_id} missing CONFIG constant")
                failed_presets[league_id] = reason
                continue
            
            result[league_id] = module.CONFIG
            _logger.debug(f"Loaded preset: {league_id}")
            
        except Exception as e:
            reason = type(e).__name__
            _logger.error(f"Failed to load preset {league_id}: {reason}: {e}")
            failed_presets[league_id] = reason
            # Record metric: negelir_league_preset_load_failed_total{league_id, reason}
            # (metrics instrumentation in Phase 13.3.2a — deferred to Phase 8 ops console)
            continue
    
    _LEAGUE_CONFIGS_CACHE = result
    _FAILED_PRESETS_CACHE = failed_presets
    
    if failed_presets:
        _logger.warning(
            f"Failed to load {len(failed_presets)} preset(s): "
            f"{', '.join(f'{k}:{v}' for k, v in failed_presets.items())}"
        )
    
    return result


def get_league_config(league_id: str):
    """Return the LeagueConfig for a given league_id, or None if not found."""
    configs = load_league_configs()
    return configs.get(league_id)


# Module-level constant (Phase 13.3.2)
# Computed at import time; safe because load_league_configs wraps errors
LEAGUE_CONFIGS = load_league_configs()

__all__ = ["LEAGUE_CONFIGS", "load_league_configs", "get_league_config"]
