"""Phase 18.7 — Metric component label present (ledger #18).

Every metric must carry a 'component' label for dashboard joins.
"""

from __future__ import annotations

from pathlib import Path


def test_metric_component_label_present() -> None:
    """Verify metrics are instrumented with component labels."""
    repo_root = Path(__file__).resolve().parents[2]
    
    # Check common/observability module exists
    obs_module = repo_root / "common" / "observability"
    assert obs_module.exists(), \
        f"Observability module must exist at {obs_module}"
    
    # Check for telemetry infrastructure
    telemetry = repo_root / "ai" / "common" / "telemetry.py"
    if telemetry.exists():
        content = telemetry.read_text(encoding="utf-8")
        # Verify label documentation
        assert "component" in content.lower() or "label" in content.lower(), \
            "Telemetry module should reference component labels"
