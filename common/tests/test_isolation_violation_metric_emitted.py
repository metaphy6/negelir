"""Phase 18.7 ledger #4 proof test: isolation violation metric is emitted."""

import sys
from pathlib import Path


def test_isolation_violation_metric_emitted() -> None:
    """Verify the isolation_violation_total metric exists and can be emitted."""
    # Import the metrics module
    sys.path.insert(0, str(Path("/home/tech/code/negelir")))
    
    from common.observability.metrics import record_isolation_violation, isolation_violation_total
    
    # Test that the metric object exists
    assert isolation_violation_total is not None
    
    # Test that we can record a violation
    record_isolation_violation(
        component="swarm",
        kind="import",
        ledger_ref="ledger_1",
    )
    
    print("✓ Isolation violation metric emitted successfully")


if __name__ == "__main__":
    test_isolation_violation_metric_emitted()
