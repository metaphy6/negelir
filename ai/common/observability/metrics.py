"""Phase 19.8 — T3 metric definitions and registry.

Per ROADMAP §19.8, T3-tier leagues have a dedicated metric set
with t3_ prefix for resource governance, staleness detection, 
and suppression tracking.
"""
from __future__ import annotations

from typing import Tuple


# T3-specific metric registry
T3_METRICS = {
    "datasource_t3_records_ingested_total",
    "datasource_t3_source_available",
    "datasource_t3_shelved",
    "datasource_t3_scrape_budget_used_s",
    "datasource_t3_budget_exhausted_total",
    "datasource_t3_staleness_alert_total",
    "datasource_t3_suppressed_predictions_total",
}


def get_metric_value(metric_name: str) -> Tuple[str, float]:
    """Get the current value of a metric.
    
    Args:
        metric_name: Name of the metric to retrieve.
        
    Returns:
        A tuple of (metric_name, value) where value is the current
        metric value (default 0.0 if not yet recorded).
    """
    # Placeholder implementation - in production, this would
    # query the metrics backend (Prometheus, CloudWatch, etc.)
    return (metric_name, 0.0)


def record_t3_ingestion(league_id: str, count: int) -> None:
    """Record T3 record ingestion event."""
    # Placeholder for metric recording
    pass


def record_t3_source_available(league_id: str, available: bool) -> None:
    """Record T3 source availability."""
    pass


def record_t3_shelved(league_id: str, shelved: bool) -> None:
    """Record T3 shelving event."""
    pass
