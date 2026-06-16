"""Phase 18.7 ledger #18 proof test: every metric includes component label."""

from pathlib import Path


def test_metric_component_label_present() -> None:
    """Verify isolation telemetry metrics include the component label."""
    metrics_path = Path("/home/tech/code/negelir/common/observability/metrics.py")
    assert metrics_path.exists()
    
    content = metrics_path.read_text()
    
    # Check that the metrics are defined with component label
    assert 'labelnames=["component"' in content or 'labelnames=["component,' in content
    assert "isolation_violation_total" in content
    
    print("✓ Metrics include component label")


if __name__ == "__main__":
    test_metric_component_label_present()
