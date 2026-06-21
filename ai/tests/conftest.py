"""Pytest configuration for the AI test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Phase 18 → Phase 22 transitional layout detection
_repo_root = Path(__file__).resolve().parent.parent.parent
_ai_path = str(_repo_root / "ai")

# Detect Phase 22 layout: root/common/config/__init__.py exists
_phase22_layout = (_repo_root / "common" / "config" / "__init__.py").exists()

# Will be set in pytest_configure
cfg = None


def pytest_configure(config):
    """Ensure cfg is imported correctly for current layout.
    
    Phase 18: ai/common/config is authoritative; put ai/ first in sys.path
    Phase 22+: common/config is authoritative; keep root first, but still add ai/ for nlp/* imports
    """
    global cfg
    
    if _phase22_layout:
        # Phase 22+ layout: common/config is canonical.
        # Ensure root is first (root conftest handles this)
        # But we also need ai/ in sys.path so that ai/nlp imports work as 'from nlp import ...'
        repo_root_str = str(_repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)
        
        # Add ai/ path after root (if not already present)
        if _ai_path not in sys.path:
            sys.path.insert(1, _ai_path)
        
        # Import from common.config (which re-exports from common.config.ai_pipeline)
        from common.config import cfg as _cfg
        cfg = _cfg
    else:
        # Phase 18 layout: ai/common/config is canonical.
        # Ensure ai/ is in sys.path before common imports
        if _ai_path in sys.path:
            sys.path.remove(_ai_path)
        sys.path.insert(0, _ai_path)
        
        # Clear any cached 'common' module to force use of ai/common
        modules_to_remove = [k for k in sys.modules.keys() if k.startswith('common')]
        for k in modules_to_remove:
            sys.modules.pop(k, None)
        
        # Import cfg from ai/common/config
        import ai.common.config as _config
        cfg = _config.cfg
    
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
    
    config.addinivalue_line(
        "markers",
        "integration: end-to-end tests that exercise real data and may be skipped "
        "when caches are missing.",
    )
    config.addinivalue_line(
        "markers",
        "chaos: Phase 12 resilience test; runs in chaos/nightly lanes, never in fast lane.",
    )


@pytest.fixture(autouse=True)
def clear_default_scaler_noise_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep AI tests deterministic regardless of the current UTC hour.

    The production default enables scaler noise windows. Most ai/tests are not
    exercising that feature and should not start failing simply because the
    suite runs during an active UTC window. Tests that cover the feature can
    override this fixture explicitly via ``monkeypatch``.
    """
    monkeypatch.setattr(cfg, "maint_scaler_noise_windows", "", raising=False)
