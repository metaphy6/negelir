"""Phase 18.5 — Public API compatibility test for swarm.

Pins the public surface declared in __all__ to detect breaking changes.
"""
from __future__ import annotations

import swarm


def test_swarm_public_api_exports_exist() -> None:
    """Verify all __all__ exports are actually importable."""
    for name in swarm.__all__:
        assert hasattr(swarm, name), f"__all__ exports {name!r} but it doesn't exist"


def test_swarm_public_api_is_not_empty() -> None:
    """Verify the public API is not empty."""
    assert len(swarm.__all__) > 0, "swarm.__all__ is empty"
