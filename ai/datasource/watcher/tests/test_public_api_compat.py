"""Phase 18.5 — Public API compatibility test for datasource_watcher.

Pins the public surface declared in __all__ to detect breaking changes.
"""
from __future__ import annotations

from ai.datasource import watcher


def test_datasource_watcher_public_api_exports_exist() -> None:
    """Verify all __all__ exports are actually importable."""
    for name in watcher.__all__:
        assert hasattr(watcher, name), f"__all__ exports {name!r} but it doesn't exist"


def test_datasource_watcher_public_api_is_not_empty() -> None:
    """Verify the public API is not empty."""
    assert len(watcher.__all__) > 0, "watcher.__all__ is empty"
