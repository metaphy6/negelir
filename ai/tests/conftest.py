"""Pytest configuration for the AI test suite."""

from __future__ import annotations

import pytest

from common.config import cfg

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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: end-to-end tests that exercise real data and may be skipped "
        "when caches are missing.",
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
