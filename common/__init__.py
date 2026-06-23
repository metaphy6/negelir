"""Common shared libraries (Phase 18 transitional).

This package provides shared infrastructure used across components.
During Phase 18 transition, actual implementations live in ai/common/ until Phase 22.

When tests run with PYTHONPATH=ai, imports like:
  from common.config import cfg
  from common.fixture_state import FixtureState

...resolve to:
  ai/common/config.py
  ai/common/fixture_state.py

The root common/ directory exists to support future Phase 22 migrations.
The common/config.py module provides a bridge for backwards-compatible imports.
"""

__all__ = [
    "cfg",
    "Record",
    "FixtureState",
    "BusClient",
]


