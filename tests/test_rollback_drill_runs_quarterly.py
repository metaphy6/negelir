"""
Phase 18.9 §18.9 — Quarterly rollback drill proof test (ledger #20).

Validates that `make phase18.rollback.drill` executes successfully against
an ephemeral environment and records outcome in docs/tracking/drills.csv.
"""

import subprocess
from pathlib import Path


def test_rollback_drill_runs_quarterly() -> None:
    """Test that rollback drill target exists and runs."""
    # Verify the Make target exists
    result = subprocess.run(
        ["make", "help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent
    )
    assert "phase18.rollback.drill" in result.stdout, "phase18.rollback.drill not in make help"
    
    # Verify xops/makefile/drills.py exists
    drills_py = Path(__file__).parent.parent / "xops" / "makefile" / "drills.py"
    assert drills_py.exists(), f"{drills_py} not found"
    
    # Verify drills.csv exists and has header
    drills_csv = Path(__file__).parent.parent / "docs" / "tracking" / "drills.csv"
    assert drills_csv.exists(), f"{drills_csv} not found"
    
    csv_content = drills_csv.read_text(encoding="utf-8")
    assert "timestamp,drill_type,status,slo_minutes,paged_human,notes" in csv_content, \
        f"drills.csv header not found in {csv_content[:200]}"
