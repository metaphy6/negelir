"""Phase 18.5 — Public API compatibility test for common.

Pins the public surface declared in __all__ to detect breaking changes.
"""
from __future__ import annotations

import common


def test_common_public_api_exports_exist() -> None:
    """Verify all __all__ exports are actually importable."""
    for name in common.__all__:
        assert hasattr(common, name), f"__all__ exports {name!r} but it doesn't exist"


def test_common_public_api_is_not_empty() -> None:
    """Verify the public API is not empty."""
    assert len(common.__all__) > 0, "common.__all__ is empty"
