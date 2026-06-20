"""Phase 19.8 — Observability module for T3 metrics and alerts.

This module provides Phase 19 observability features (T3 metrics and staleness alerts).
For Phase 22+, this will be re-exported from the root common.observability module.
"""
from __future__ import annotations

# For Phase 19, re-export from local modules
# For Phase 22+, these would come from the root common/ package
try:
    # Try to import from root common first (Phase 22+ layout)
    from common.observability import metrics as _common_metrics
    from common.observability import alerts as _common_alerts
    metrics = _common_metrics
    alerts = _common_alerts
except ImportError:
    # Fall back to local modules (Phase 19 layout)
    from . import metrics
    from . import alerts

__all__ = ['metrics', 'alerts']

