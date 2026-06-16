"""Pytest configuration for the AI test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Phase 18: ai/ layout is transitional; we'll adjust sys.path in pytest_configure before importing cfg
_repo_root = Path(__file__).resolve().parent.parent.parent
_ai_path = str(_repo_root / "ai")

# Will be set in pytest_configure
cfg = None


def pytest_configure(config):
    """Ensure ai/ is in sys.path for Phase 18 transitional layout and import cfg."""
    global cfg
    
    # Move ai to front if it's not already (root conftest may have put root first)
    if _ai_path in sys.path:
        sys.path.remove(_ai_path)
    sys.path.insert(0, _ai_path)
    
    # Clear any cached 'common' module from sys.modules that may have been cached as root/common
    # This forces re-import to use ai/common instead
    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('common')]
    for k in modules_to_remove:
        sys.modules.pop(k, None)
    
    # Now import cfg with correct sys.path
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
