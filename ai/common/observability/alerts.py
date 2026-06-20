"""Phase 19.8 — Alert reactors for T3 observability."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Import for staleness checking (test patches this path)
import common.observability.metrics


@dataclass
class Alert:
    """Alert object."""
    kind: str
    league_id: str
    message: str = ""
    severity: str = "warning"


@dataclass
class RobotsAlert:
    """Alert for robots.txt changes."""
    kind: str
    source: str
    severity: str = "warn"
    message: str = ""


class T3StalenessAlertReactor:
    """Detects staleness in T3-tier pipeline.
    
    Per ROADMAP §19.8, T3 staleness alerts fire when a league's 
    datasource has not ingested new records for a configured threshold
    (default 72 hours).
    """
    
    def __init__(self, staleness_hours: int = 72):
        """Initialize T3 staleness reactor.
        
        Args:
            staleness_hours: Hours of inactivity before alert fires.
        """
        self.staleness_hours = staleness_hours
    
    def check_league_staleness(self, league_id: str) -> Optional[Alert]:
        """Check if a league's pipeline is stale.
        
        Args:
            league_id: League to check.
            
        Returns:
            Alert object if stale, None if active.
        """
        # Get the metric value (returns tuple of (value, hours_since_last_update))
        try:
            current_val, hours_ago = common.observability.metrics.get_metric_value(
                f"datasource_t3_records_ingested_total:{league_id}"
            )
        except (TypeError, ValueError, KeyError, AttributeError):
            # Fallback for when metric is not available
            return None
        
        # Fire alert if hours_ago exceeds threshold
        if hours_ago > self.staleness_hours:
            return Alert(
                kind='t3_pipeline_stale',
                league_id=league_id,
                message=f"T3 pipeline stale for {hours_ago} hours (threshold: {self.staleness_hours}h)",
                severity="warning"
            )
        
        return None

