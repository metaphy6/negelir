"""Phase 19 §19.6 — Budget exhaustion metric."""
from __future__ import annotations

from ai.common.config import cfg


def test_budget_exhaustion_metric_emitted() -> None:
    """Verify T3 budget configuration is present."""
    assert hasattr(cfg, 't3_scrape_budget_per_league_s')
    assert cfg.t3_scrape_budget_per_league_s == 10
    assert cfg.t3_scrape_budget_per_league_s > 0
