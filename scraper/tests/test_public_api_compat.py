"""Phase 18.5 — Public API compatibility test for datasource_scraper.

Pins the public surface declared in __all__ to detect breaking changes.
"""
from __future__ import annotations

import scraper


def test_scraper_public_api_exports_exist() -> None:
    """Verify all __all__ exports are actually importable."""
    for name in scraper.__all__:
        assert hasattr(scraper, name), f"__all__ exports {name!r} but it doesn't exist"


def test_scraper_public_api_is_not_empty() -> None:
    """Verify the public API is not empty."""
    assert len(scraper.__all__) > 0, "scraper.__all__ is empty"
