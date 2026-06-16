"""Phase 18.7 ledger #4 proof test: relax hatch metric exists."""

import sys
from pathlib import Path


def test_relax_hatch_metric() -> None:
    """Verify the isolation_relax_hatch_active metric exists."""
    sys.path.insert(0, str(Path("/home/tech/code/negelir")))
    
    from common.observability.metrics import (
        set_isolation_relax_hatch_active,
        isolation_relax_hatch_active,
    )
    
    # Test that the metric object exists
    assert isolation_relax_hatch_active is not None
    
    # Test that we can set the value
    set_isolation_relax_hatch_active(True)  # Active
    set_isolation_relax_hatch_active(False)  # Inactive
    
    print("✓ Relax hatch metric set successfully")


if __name__ == "__main__":
    test_relax_hatch_metric()
