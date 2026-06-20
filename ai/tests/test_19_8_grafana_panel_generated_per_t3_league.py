"""Phase 19 §19.8 — Grafana panels auto-generated per T3 league."""
import pytest


def test_grafana_panel_generated_per_t3_league():
    """Each T3 league gets a Grafana row with the 5 T3 metrics."""
    from xops.provisioning.grafana_provisioner import GrafanaProvisioner
    
    provisioner = GrafanaProvisioner()
    # Mock T3 leagues
    provisioner._t3_leagues = ["br_serie_a", "cn_super_league"]
    
    panels = provisioner.generate_t3_panels()
    assert len(panels) == 2
    
    for league_id, panel_row in panels.items():
        assert "title" in panel_row
        assert league_id in panel_row["title"]
        assert "collapsed" in panel_row
        assert panel_row["collapsed"] is True


def test_grafana_panel_contains_t3_metrics():
    """Generated panel row contains all 5 T3 metrics."""
    from xops.provisioning.grafana_provisioner import GrafanaProvisioner
    
    provisioner = GrafanaProvisioner()
    panel = provisioner.generate_single_t3_panel("br_serie_a")
    
    assert "panels" in panel
    metric_titles = [p.get("title") for p in panel["panels"]]
    
    required_metrics = [
        "records_ingested_total",
        "source_available",
        "shelved",
        "scrape_budget_used",
        "budget_exhausted_total",
    ]
    for metric in required_metrics:
        assert any(metric in title for title in metric_titles), f"Missing metric: {metric}"
