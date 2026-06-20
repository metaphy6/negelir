"""Phase 19 §19.8 — T3 staleness alert fires after timeout."""
import pytest
from unittest.mock import Mock, patch
from ai.common.observability.alerts import T3StalenessAlertReactor


def test_t3_staleness_alert_fires(tmp_path):
    """T3 pipeline staleness alert fires after threshold."""
    reactor = T3StalenessAlertReactor(staleness_hours=72)
    # Simulated league with no ingests in >72h
    with patch('common.observability.metrics.get_metric_value') as mock_metric:
        mock_metric.return_value = (0, 100)  # (current_val, last_update_hours_ago)
        alert = reactor.check_league_staleness(league_id="br_serie_a")
        assert alert is not None
        assert alert.kind == 't3_pipeline_stale'


def test_t3_staleness_alert_time_based():
    """Alert only fires if staleness exceeds configured threshold."""
    reactor = T3StalenessAlertReactor(staleness_hours=72)
    with patch('common.observability.metrics.get_metric_value') as mock_metric:
        # Recent ingests - no alert
        mock_metric.return_value = (100, 24)  # last update 24h ago
        alert = reactor.check_league_staleness(league_id="br_serie_a")
        assert alert is None
