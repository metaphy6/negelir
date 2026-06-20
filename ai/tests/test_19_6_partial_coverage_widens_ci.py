"""Phase 19 §19.6 — Partial coverage CI widening."""
from __future__ import annotations

from ai.common.config import cfg


def test_partial_coverage_widens_ci() -> None:
    """Verify partial coverage CI widen factor is configured."""
    assert hasattr(cfg, 't3_partial_coverage_ci_widen_factor')
    assert cfg.t3_partial_coverage_ci_widen_factor == 1.3
    assert cfg.t3_partial_coverage_ci_widen_factor > 1.0
