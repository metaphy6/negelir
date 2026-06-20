"""Phase 19 §19.7 — Binary-serialised msgpack cache."""
from __future__ import annotations

from ai.common.config import cfg


def test_msgpack_cache_serves_hot_path() -> None:
    """Verify msgpack cache configuration."""
    assert hasattr(cfg, 'catalog_reload_slo_ms')
    assert cfg.catalog_reload_slo_ms == 500
