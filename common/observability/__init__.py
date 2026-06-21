"""
Observability & telemetry infrastructure for Negelir.
Metric names follow Phase 18.7 ledger #18 pattern: {component}_{subsystem}_{verb}_{unit}
"""

from .alerts import Alert, T3Alert, T3StalenessAlertReactor, T3SLOExclusionGate, RobotsAlert
from .metrics import (
    isolation_violation_total,
    isolation_audit_age_seconds,
    isolation_relax_hatch_active,
    T3_METRICS,
    record_t3_ingestion,
    record_t3_source_available,
    record_t3_shelved,
)

__all__ = [
    # Alert classes
    "Alert",
    "T3Alert",
    "T3StalenessAlertReactor",
    "T3SLOExclusionGate",
    "RobotsAlert",
    # Isolation metrics
    "isolation_violation_total",
    "isolation_audit_age_seconds",
    "isolation_relax_hatch_active",
    # T3 metrics
    "T3_METRICS",
    "record_t3_ingestion",
    "record_t3_source_available",
    "record_t3_shelved",
]
