"""Pytest configuration for the AI test suite."""

from __future__ import annotations

import pytest

from common.config import cfg


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
