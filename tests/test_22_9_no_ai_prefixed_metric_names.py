"""Phase 22.9 §22.9.7 — Proof test: no ai_-prefixed metric names after migration."""
import re
from pathlib import Path


def test_no_ai_prefixed_metrics_in_telemetry():
    """Verify that all metrics have been migrated away from ai_ prefix."""
    telemetry_path = Path("/home/tech/code/negelir/common/telemetry.py")
    assert telemetry_path.exists(), f"{telemetry_path} not found"
    
    content = telemetry_path.read_text()
    
    # Look for any metric string literals with ai_ prefix
    ai_prefixed_pattern = re.compile(r'["\']ai_[a-z0-9_]+["\']')
    matches = ai_prefixed_pattern.findall(content)
    assert not matches, f"Found ai_-prefixed metrics: {matches}"


def test_no_ai_prefixed_metrics_in_observability():
    """Verify observability metrics don't use ai_ prefix."""
    metrics_path = Path("/home/tech/code/negelir/common/observability/metrics.py")
    assert metrics_path.exists()
    
    content = metrics_path.read_text()
    ai_prefixed_pattern = re.compile(r'["\']ai_[a-z0-9_]+["\']')
    matches = ai_prefixed_pattern.findall(content)
    assert not matches, f"Found ai_-prefixed metrics in observability: {matches}"
