"""
Phase 18.9 §18.9 — Burn-in metrics published to observability layer (ledger #29).

Phase 14 panel surfaces four burn-in metrics with single "Phase 18 burn-in" status:
1. rollback_drill_success_count + rollback_drill_missed_count
2. isolation_regression_count
3. shim_resurrection_pr_count
4. relax_invocation_count (prod)
"""

from common.observability import metrics


def test_burn_in_metrics_published() -> None:
    """Test that all four burn-in metrics are available."""
    # Verify metrics exist (even if Prometheus is unavailable, stubs exist)
    assert hasattr(metrics, "rollback_drill_success_count"), "rollback_drill_success_count not found"
    assert hasattr(metrics, "rollback_drill_missed_count"), "rollback_drill_missed_count not found"
    assert hasattr(metrics, "isolation_regression_count"), "isolation_regression_count not found"
    assert hasattr(metrics, "shim_resurrection_pr_count"), "shim_resurrection_pr_count not found"
    assert hasattr(metrics, "relax_invocation_count"), "relax_invocation_count not found"
    
    # Verify helper functions exist
    assert hasattr(metrics, "record_rollback_drill_success"), "record_rollback_drill_success not found"
    assert hasattr(metrics, "record_rollback_drill_missed"), "record_rollback_drill_missed not found"
    assert hasattr(metrics, "record_isolation_regression"), "record_isolation_regression not found"
    assert hasattr(metrics, "record_shim_resurrection_pr"), "record_shim_resurrection_pr not found"
    assert hasattr(metrics, "record_relax_invocation"), "record_relax_invocation not found"
