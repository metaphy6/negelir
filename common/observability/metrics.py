"""
Isolation telemetry metrics (Phase 18.7 ledger #4).

Metrics follow the naming pattern {component}_{subsystem}_{verb}_{unit}.
All metrics include a 'component' label for dashboard join operations.
"""

import time
from typing import Optional

try:
    from prometheus_client import Counter, Gauge
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


# Phase 18.7 ledger #4 — Isolation violation metric
# Emitted when an isolation constraint is violated (ledger entries #1-#56)
# Should be zero in steady state; non-zero triggers paging within 60 seconds
if _PROMETHEUS_AVAILABLE:
    isolation_violation_total = Counter(
        "common_isolation_violation_total",
        "Isolation constraint violations (should be zero in steady state)",
        labelnames=["component", "kind", "ledger_ref"],
    )
    
    # Phase 18.7 ledger #4 — Isolation audit age gauge
    # Tracks how long since the last isolation audit ran
    # Configured to page if > cfg.isolation_audit_max_age_days (default 100 days in seconds)
    isolation_audit_age_seconds = Gauge(
        "common_isolation_audit_age_seconds",
        "Age in seconds since last isolation audit",
    )
    
    # Phase 18.7 ledger #4 — Isolation relax hatch active gauge
    # Binary gauge: 1 if RELAX_ISOLATION_FOR_ROLLBACK is active, 0 otherwise
    # Alert if value is 1 longer than auto-unset window (cfg.isolation_relax_max_hours, default 72 h)
    isolation_relax_hatch_active = Gauge(
        "common_isolation_relax_hatch_active",
        "Binary gauge: 1 if isolation relax hatch is active (rollback mode)",
    )
else:
    # No-op stubs when Prometheus is unavailable
    class _NoOpCounter:
        def labels(self, **kwargs):
            return self
        def inc(self, amount=1):
            pass
    
    class _NoOpGauge:
        def set(self, value):
            pass
    
    isolation_violation_total = _NoOpCounter()
    isolation_audit_age_seconds = _NoOpGauge()
    isolation_relax_hatch_active = _NoOpGauge()


def record_isolation_violation(
    component: str,
    kind: str,
    ledger_ref: str,
) -> None:
    """Record an isolation constraint violation.
    
    Args:
        component: The component that violated the constraint (datasource, swarm, server, etc.)
        kind: Type of violation (import, volume_mount, env_var, etc.)
        ledger_ref: Reference to the ledger row (e.g., "ledger_1", "ledger_28")
    """
    isolation_violation_total.labels(
        component=component,
        kind=kind,
        ledger_ref=ledger_ref,
    ).inc()


def set_isolation_audit_age(age_seconds: float) -> None:
    """Update the isolation audit age metric.
    
    Args:
        age_seconds: Time in seconds since the last audit ran.
    """
    isolation_audit_age_seconds.set(age_seconds)


def set_isolation_relax_hatch_active(active: bool) -> None:
    """Update the isolation relax hatch state.
    
    Args:
        active: True if the relax hatch is currently active (rollback mode).
    """
    isolation_relax_hatch_active.set(1.0 if active else 0.0)


# Phase 18.9 — Burn-in metrics (drills & recovery gates, ledgers #20, #29)
# The four burn-in metrics form a single "Phase 18 burn-in" status:
# - rollback_drill_success_count + rollback_drill_missed_count (drill SLO)
# - isolation_regression_count (post-gate isolation gate)
# - shim_resurrection_pr_count (shim deletion verification)
# - relax_invocation_count (production rollback-mode escape hatch)
if _PROMETHEUS_AVAILABLE:
    rollback_drill_success_count = Counter(
        "common_phase18_rollback_drill_success_total",
        "Successful quarterly rollback drills (Phase 18.9 ledger #20)",
    )
    
    rollback_drill_missed_count = Counter(
        "common_phase18_rollback_drill_missed_total",
        "Missed quarterly rollback drills (Phase 18.9 ledger #20); two consecutive → remove hatch",
    )
    
    isolation_regression_count = Counter(
        "common_phase18_isolation_regression_total",
        "Post-gate isolation regressions (Phase 18.9 ledger #29 burn-in gate)",
    )
    
    shim_resurrection_pr_count = Counter(
        "common_phase18_shim_resurrection_pr_total",
        "PRs that resurrect already-deleted shim files (Phase 18.9 ledger #29 burn-in gate)",
    )
    
    relax_invocation_count = Counter(
        "common_phase18_relax_invocation_total",
        "Production invocations of RELAX_ISOLATION_FOR_ROLLBACK hatch (Phase 18.9 ledger #29 burn-in gate)",
        labelnames=["context"],  # rollback, emergency, other
    )
else:
    # No-op stubs
    rollback_drill_success_count = _NoOpCounter()
    rollback_drill_missed_count = _NoOpCounter()
    isolation_regression_count = _NoOpCounter()
    shim_resurrection_pr_count = _NoOpCounter()
    
    class _NoOpCounterWithLabels:
        def labels(self, **kwargs):
            return self
        def inc(self, amount=1):
            pass
    
    relax_invocation_count = _NoOpCounterWithLabels()


def record_rollback_drill_success() -> None:
    """Record a successful quarterly rollback drill."""
    rollback_drill_success_count.inc()


def record_rollback_drill_missed() -> None:
    """Record a missed quarterly rollback drill."""
    rollback_drill_missed_count.inc()


def record_isolation_regression() -> None:
    """Record a post-gate isolation regression during burn-in."""
    isolation_regression_count.inc()


def record_shim_resurrection_pr() -> None:
    """Record a PR that resurrects a deleted shim file."""
    shim_resurrection_pr_count.inc()


def record_relax_invocation(context: str = "other") -> None:
    """Record a production invocation of the relax hatch.
    
    Args:
        context: The context for the invocation (rollback, emergency, other).
    """
    relax_invocation_count.labels(context=context).inc()
