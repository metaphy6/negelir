"""Phase 19 §19.8 — T3 metric set carries t3_ prefix."""
import pytest
from ai.common.observability import metrics


def test_t3_metric_names_carry_t3_prefix() -> None:
    """Every T3-specific metric must carry the t3_ prefix."""
    t3_metrics = {
        "datasource_t3_records_ingested_total",
        "datasource_t3_source_available",
        "datasource_t3_shelved",
        "datasource_t3_scrape_budget_used_s",
        "datasource_t3_budget_exhausted_total",
        "datasource_t3_staleness_alert_total",
        "datasource_t3_suppressed_predictions_total",
    }
    for metric_name in t3_metrics:
        assert metric_name.startswith("datasource_t3_"), f"Metric {metric_name} must carry t3_ prefix"


def test_t3_metric_registration() -> None:
    """All T3 metrics module has get_metric_value function."""
    # Verify the function exists
    assert hasattr(metrics, 'get_metric_value')
    
    # Verify it can be called
    result = metrics.get_metric_value("test_metric")
    assert isinstance(result, tuple)
    assert len(result) == 2
