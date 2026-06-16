"""Phase 18.7 ledger #4 proof test: isolation audit age metric exists."""

import sys
from pathlib import Path


def test_isolation_audit_age_metric() -> None:
    """Verify the isolation_audit_age_seconds metric exists."""
    sys.path.insert(0, str(Path("/home/tech/code/negelir")))
    
    from common.observability.metrics import set_isolation_audit_age, isolation_audit_age_seconds
    
    # Test that the metric object exists
    assert isolation_audit_age_seconds is not None
    
    # Test that we can set the value
    set_isolation_audit_age(3600.0)  # 1 hour
    
    print("✓ Isolation audit age metric set successfully")


if __name__ == "__main__":
    test_isolation_audit_age_metric()
