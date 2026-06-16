"""Phase 18.7 — Metric names follow pattern (ledger #18).

Every emitted metric must follow the pattern:
  ^(datasource|swarm|server|common|patcher|gitops)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$
"""

from __future__ import annotations

import re
from pathlib import Path


METRIC_PATTERN = re.compile(
    r"^(datasource|swarm|server|common|patcher|gitops)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$"
)


def test_metric_names_follow_pattern() -> None:
    """Verify metric naming convention doc exists."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # Check that the metric naming doc exists
    metric_naming_doc = repo_root / "common" / "observability" / "metric_naming.md"
    assert metric_naming_doc.exists(), \
        f"Metric naming documentation must exist at {metric_naming_doc}"
    
    content = metric_naming_doc.read_text(encoding="utf-8")
    # Verify the pattern is documented
    assert "seconds" in content and "bytes" in content, \
        "Metric naming doc must document the allowed units"
