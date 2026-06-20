"""Auto-generate Grafana panels for T3 leagues."""
from __future__ import annotations
from typing import Optional, Dict, List


class GrafanaProvisioner:
    """Generate Grafana dashboards and alert rules for T3 leagues."""
    
    def __init__(self):
        self._t3_leagues: List[str] = []
    
    def generate_t3_panels(self) -> Dict[str, dict]:
        """Generate a Grafana row per T3 league with the 5 T3 metrics."""
        panels = {}
        for league_id in self._t3_leagues:
            panels[league_id] = {
                "title": f"T3 League: {league_id}",
                "collapsed": True,
                "panels": self._generate_metrics_panels(league_id),
            }
        return panels
    
    def generate_single_t3_panel(self, league_id: str) -> dict:
        """Generate a Grafana row for a single T3 league."""
        return {
            "title": f"T3 League: {league_id}",
            "collapsed": True,
            "panels": self._generate_metrics_panels(league_id),
        }
    
    def _generate_metrics_panels(self, league_id: str) -> List[dict]:
        """Generate panels for the 5 core T3 metrics."""
        metrics = [
            {
                "title": "records_ingested_total",
                "targets": [{"expr": f'datasource_t3_records_ingested_total{{league_id="{league_id}"}}'}]
            },
            {
                "title": "source_available",
                "targets": [{"expr": f'datasource_t3_source_available{{league_id="{league_id}"}}'}]
            },
            {
                "title": "shelved",
                "targets": [{"expr": f'datasource_t3_shelved{{league_id="{league_id}"}}'}]
            },
            {
                "title": "scrape_budget_used",
                "targets": [{"expr": f'datasource_t3_scrape_budget_used_s{{league_id="{league_id}"}}'}]
            },
            {
                "title": "budget_exhausted_total",
                "targets": [{"expr": f'datasource_t3_budget_exhausted_total{{league_id="{league_id}"}}'}]
            },
        ]
        return metrics
    
    def generate_t3_alert_rules(self) -> List[dict]:
        """Generate alert rules for T3 staleness per league."""
        from common.config import cfg
        
        rules = []
        for league_id in self._t3_leagues:
            rules.append({
                "alert": f"T3PipelineStale{league_id.upper()}",
                "condition": f'datasource_t3_records_ingested_total{{league_id="{league_id}"}} < {cfg.t3_staleness_alert_hours}h',
                "routeLabel": "ops-admin",
            })
        return rules
    
    def generate_single_t3_alert_rule(self, league_id: str) -> dict:
        """Generate alert rule for a single T3 league."""
        from common.config import cfg
        
        return {
            "alert": f"T3PipelineStale{league_id.upper()}",
            "condition": f'datasource_t3_records_ingested_total{{league_id="{league_id}"}} < {cfg.t3_staleness_alert_hours}h',
            "routeLabel": "ops-admin",
        }


# Grafana template reference
T3_GRAFANA_ALERT_RULE = {
    "alert": "T3PipelineStale",
    "condition": "datasource_t3_records_ingested_total < 72h",
    "routeLabel": "ops-admin",
}
