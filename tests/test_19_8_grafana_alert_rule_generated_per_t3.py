"""Phase 19 §19.8 — Grafana alert rules generated per T3 league."""
import pytest


def test_grafana_alert_rule_generated_per_t3():
    """Each T3 league gets an alert rule for staleness."""
    from xops.provisioning.grafana_provisioner import GrafanaProvisioner
    
    provisioner = GrafanaProvisioner()
    provisioner._t3_leagues = ["br_serie_a"]
    
    alert_rules = provisioner.generate_t3_alert_rules()
    assert len(alert_rules) == 1
    
    rule = alert_rules[0]
    assert "datasource_t3_records_ingested_total" in rule["condition"]


def test_alert_rule_references_staleness_threshold():
    """Alert rule uses configured staleness threshold."""
    from xops.provisioning.grafana_provisioner import GrafanaProvisioner
    from ai.common.config import cfg
    
    provisioner = GrafanaProvisioner()
    rule = provisioner.generate_single_t3_alert_rule("br_serie_a")
    
    # Rule should reference the configured threshold
    assert f"{cfg.t3_staleness_alert_hours}h" in rule["condition"]
