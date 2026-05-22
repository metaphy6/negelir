from __future__ import annotations

import pytest

from common.config import cfg


@pytest.fixture(autouse=True)
def clear_default_scaler_noise_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep maint tests deterministic regardless of the current UTC hour.

    Phase 8.15.9 introduced time-based default noise windows. Most maint tests
    are not exercising that feature and should not start failing just because
    the suite happens to run during an active window. Tests that do cover the
    feature override this fixture explicitly via ``monkeypatch``.
    """
    monkeypatch.setattr(cfg, "maint_scaler_noise_windows", "", raising=False)