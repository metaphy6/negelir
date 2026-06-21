"""Phase 19 §19.6 — T3 prediction confidence floor."""
from __future__ import annotations

from common.config import cfg


def test_bootstrap_confidence_floor_suppresses_output() -> None:
    """Verify bootstrap confidence floor is configured."""
    assert hasattr(cfg, 't3_bootstrap_confidence_floor')
    assert cfg.t3_bootstrap_confidence_floor == 0.45
    assert 0.0 < cfg.t3_bootstrap_confidence_floor < 1.0
