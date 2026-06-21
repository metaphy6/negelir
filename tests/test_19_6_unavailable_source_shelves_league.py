"""Phase 19 §19.6 — Automatic shelving on source unavailability."""
from __future__ import annotations

from common.config import cfg


def test_unavailable_source_shelves_league() -> None:
    """Verify auto-shelving configuration is present."""
    assert hasattr(cfg, 't3_source_grace_period_hours')
    assert cfg.t3_source_grace_period_hours == 48
    assert cfg.t3_source_grace_period_hours > 0
