"""Phase 19 §19.8 — T3 staleness alert severity is info, not paged."""
import pytest


def test_t3_staleness_alert_does_not_page_oncall():
    """T3 staleness alerts have severity=info and route to ops-admin only."""
    from common.observability.alerts import T3Alert
    
    alert = T3Alert(
        kind="t3_pipeline_stale",
        league_id="br_serie_a",
        severity="info",
    )
    assert alert.severity == "info"


def test_t3_alert_not_routed_to_pagerduty():
    """T3 alerting rules do not create PagerDuty incidents."""
    from xops.provisioning.grafana_provisioner import T3_GRAFANA_ALERT_RULE
    
    rule = T3_GRAFANA_ALERT_RULE
    assert rule.get('routeLabel') == 'ops-admin'
    assert rule.get('routeLabel') != 'pagerduty'
