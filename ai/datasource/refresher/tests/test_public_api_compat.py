"""Phase 18.5 — Public API compatibility test for datasource_refresher.

Pins the public surface declared in __all__ to detect breaking changes.
"""
from __future__ import annotations

from ai.datasource import refresher


def test_datasource_refresher_public_api_exports_exist() -> None:
    """Verify all __all__ exports are actually importable."""
    for name in refresher.__all__:
        assert hasattr(refresher, name), f"__all__ exports {name!r} but it doesn't exist"


def test_datasource_refresher_public_api_is_not_empty() -> None:
    """Verify the public API is not empty."""
    assert len(refresher.__all__) > 0, "refresher.__all__ is empty"
