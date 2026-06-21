"""Phase 19 §19.6 — T3 compute cap."""
from __future__ import annotations

from common.config import cfg


def test_t3_compute_cap_enforced() -> None:
    """Verify T3 compute cap configuration is present and correctly bounded."""
    assert hasattr(cfg, 't3_predictor_max_cpu_cores')
    assert cfg.t3_predictor_max_cpu_cores == 0.25
    assert cfg.t3_predictor_max_cpu_cores > 0.0
    assert cfg.t3_predictor_max_cpu_cores < 1.0
