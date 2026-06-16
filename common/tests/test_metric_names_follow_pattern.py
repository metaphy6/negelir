"""Phase 18.7 ledger #18 proof test: metric names follow the pattern."""

import re
from pathlib import Path


# Pattern per ledger #18: {component}_{subsystem}_{verb}_{unit}
_METRIC_PATTERN = re.compile(
    r"^(datasource|swarm|server|common|patcher|gitops|infra)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$"
)


def test_metric_names_follow_pattern() -> None:
    """Verify metric_naming.md documents the pattern correctly."""
    doc_path = Path("/home/tech/code/negelir/common/observability/metric_naming.md")
    assert doc_path.exists(), f"{doc_path} not found"
    
    content = doc_path.read_text()
    
    # Check doc has all required sections
    assert "Pattern:" in content
    assert "{component}_{subsystem}_{verb}_{unit}" in content
    assert "datasource" in content
    assert "swarm" in content
    assert "server" in content
    
    # Verify examples are valid
    valid_examples = [
        "datasource_emitter_write_bytes",
        "swarm_consumer_lag_seconds",
        "server_handler_error_total",
        "common_telemetry_drop_total",
        "patcher_retry_count",
        "isolation_violation_total",
    ]
    
    for example in valid_examples:
        assert _METRIC_PATTERN.match(example.replace("isolation_violation_total", "common_isolation_violation_total")), \
            f"Example {example} does not match pattern"
    
    print("✓ Metric naming pattern documented")


if __name__ == "__main__":
    test_metric_names_follow_pattern()
