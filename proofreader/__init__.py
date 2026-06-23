"""Negelir — Proofreader (validation and drift detection).

Pivot v3 component: proofreader (moved from ai/proofreader/ in Phase 22.4).

Phase 6 component: validates predictions, detects drift, and ensures
model output quality and consistency.

Public API: validation, drift detection, data quality checks.
"""

__all__ = [
    "Validator",
    "CrossValidator",
    "DriftDetector",
]
