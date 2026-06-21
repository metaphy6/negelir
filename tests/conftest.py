"""Consolidated pytest configuration for root-level tests/

Merges the responsibilities of:
- Root conftest.py (Phase 22 layout detection, global markers, backup perms)
- ai/tests/conftest.py (cfg import, hypothesis setup, AI markers, scaler fixture)

This file consolidates test infrastructure per Ledger Row #3 and #21
(docs/planning/ROADMAP.md §22.0) and
docs/decisions/phase22/conftest_consolidation.md (Phase 22.3b bullet 1).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Root and layout detection
ROOT = Path(__file__).resolve().parent.parent
_root_str = str(ROOT)
_ai_path = str(ROOT / "ai")

# Phase 18 → Phase 22 transitional layout detection
# Phase 22+: root/common/config/__init__.py exists; Phase 18 does not
_phase22_layout = (ROOT / "common" / "config" / "__init__.py").exists()

# Set up sys.path based on layout (BEFORE importing cfg)
if _phase22_layout:
    # Phase 22+: ensure repo root is first; ai/ second (for nlp/* imports)
    if _ai_path in sys.path:
        sys.path.remove(_ai_path)
    if _root_str in sys.path:
        sys.path.remove(_root_str)
    sys.path.insert(0, _root_str)
    # Add ai/ at position 1 for nlp/* imports to resolve from ai/nlp/
    # (transitional: ai/tests will have moved here, but still imports 'from nlp')
    sys.path.insert(1, _ai_path)
else:
    # Phase 18: ai/ must be first for ai.common to resolve
    if _root_str in sys.path:
        sys.path.remove(_root_str)
    if _ai_path in sys.path:
        sys.path.remove(_ai_path)
    sys.path.insert(0, _ai_path)

# Import cfg from the correct location based on layout
# This import must happen AFTER sys.path is correctly set
if _phase22_layout:
    # Phase 22+: common/config is canonical (at root)
    # The root __init__.py re-exports from common/config/ai_pipeline
    from common.config import cfg as _cfg
else:
    # Phase 18: ai/common/config is canonical
    # Clear any cached 'common' module to force use of ai/common
    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('common')]
    for k in modules_to_remove:
        sys.modules.pop(k, None)
    import ai.common.config as _config
    _cfg = _config.cfg

cfg = _cfg


def pytest_configure(config):  # noqa: D401
    """Configure pytest: markers, hypothesis, layout setup."""
    
    if _phase22_layout:
        # Double-check layout (root should be first in sys.path)
        if _root_str in sys.path:
            sys.path.remove(_root_str)
        sys.path.insert(0, _root_str)
        
        # Clear stale ai/common import if present
        if 'common' in sys.modules:
            common_module = sys.modules['common']
            if hasattr(common_module, '__file__') and common_module.__file__:
                if '/ai/common' in common_module.__file__:
                    sys.modules.pop('common', None)
                    # Also remove submodules
                    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('common.')]
                    for k in modules_to_remove:
                        sys.modules.pop(k, None)
    
    # Phase 10 §10.21.1 — Pin hypothesis settings globally for NLP suite.
    # Without database=None, CI cache divergence makes shrink-to-different-counterexample
    # non-deterministic. derandomize=True ensures the same failing input each run.
    try:
        from hypothesis import settings
        settings.register_profile(
            "nlp_ci",
            database=None,
            derandomize=True,
            max_examples=cfg.nlp_hypothesis_max_examples,
        )
        settings.load_profile("nlp_ci")
    except ImportError:
        # hypothesis not installed — property tests will be skipped anyway
        pass
    
    # Global pytest markers (from root conftest.py)
    config.addinivalue_line(
        "markers",
        "live: opt-in tests that hit real upstreams (RUN_LIVE_TESTS=1)",
    )
    config.addinivalue_line(
        "markers",
        "cpu_only: Phase 11 parity tests — predictor / model output must be "
        "identical (or within ε) on CPU vs the chosen device.",
    )
    config.addinivalue_line(
        "markers",
        "slow: tests that take noticeable wall time (CPU/GPU parity sweeps, "
        "full-pipeline runs). Excluded by `make test.fast`; included by "
        "`make test.ai` and CI.",
    )
    
    # AI-layer pytest markers (from ai/tests/conftest.py)
    config.addinivalue_line(
        "markers",
        "integration: end-to-end tests that exercise real data and may be skipped "
        "when caches are missing.",
    )
    config.addinivalue_line(
        "markers",
        "chaos: Phase 12 resilience test; runs in chaos/nightly lanes, never in fast lane.",
    )
    
    # Enforce backup directory permissions (from root conftest.py)
    backup_dir = ROOT / "data" / "backups"
    if backup_dir.is_dir():
        for path in backup_dir.iterdir():
            if path.is_file():
                current = path.stat().st_mode & 0o777
                if current > 0o600:
                    os.chmod(path, 0o600)


@pytest.fixture(autouse=True)
def clear_default_scaler_noise_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic regardless of the current UTC hour.

    The production default enables scaler noise windows (Phase 8.15.9).
    Most tests are not exercising that feature and should not start failing
    simply because the suite runs during an active UTC window. Tests that cover
    the feature can override this fixture explicitly via ``monkeypatch``.
    """
    monkeypatch.setattr(cfg, "maint_scaler_noise_windows", "", raising=False)
