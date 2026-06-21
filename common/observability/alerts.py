"""T3 observability alerts — staleness detection and SLO gates."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import time

from common.config import cfg
from common.observability import metrics


@dataclass
class Alert:
    """Generic alert object for observability events."""
    kind: str
    league_id: str
    message: str = ""
    severity: str = "warning"


@dataclass
class T3Alert:
    """T3 alert payload."""
    kind: str
    league_id: str
    severity: str = "info"
    message: str = ""
    metadata: dict = None


class T3StalenessAlertReactor:
    """Detects and emits staleness alerts for T3 pipelines."""
    
    def __init__(self, staleness_hours: int = 72):
        self.staleness_hours = staleness_hours
        self._last_check: dict[str, float] = {}
    
    def check_league_staleness(
        self,
        league_id: str,
        current_ingested_count: int = 0,
        last_ingest_timestamp: Optional[float] = None,
    ) -> Optional[T3Alert]:
        """Check if a T3 league has been stale for too long.
        
        Returns:
            T3Alert if staleness threshold exceeded, else None.
        """
        # Fetch metric value using the metrics module
        if last_ingest_timestamp is None:
            metric_value, staleness_hours = metrics.get_metric_value(
                f"datasource_t3_records_ingested_total",
                league_id=league_id
            )
            current_ingested_count = int(metric_value)
        else:
            staleness_seconds = (time.time() - last_ingest_timestamp)
            staleness_hours = staleness_seconds / 3600.0
        
        if staleness_hours > self.staleness_hours:
            return T3Alert(
                kind="t3_pipeline_stale",
                league_id=league_id,
                severity="info",
                message=f"T3 pipeline for {league_id} has not ingested records for {staleness_hours:.1f}h",
                metadata={
                    "hours_stale": staleness_hours,
                    "threshold_hours": self.staleness_hours,
                    "last_ingest_count": current_ingested_count,
                }
            )
        
        return None


class T3SLOExclusionGate:
    """Ensures T3 leagues are excluded from T1/T2 SLO calculations."""
    
    @staticmethod
    def is_eligible_for_t1_t2_slo(tier: str) -> bool:
        """Check if a league tier should be included in T1/T2 SLOs."""
        return tier in ("T1", "T2")
    
    @staticmethod
    def filter_slo_records(records: list[dict]) -> list[dict]:
        """Remove T3 records from SLO calculation."""
        return [r for r in records if T3SLOExclusionGate.is_eligible_for_t1_t2_slo(r.get("tier", "T3"))]


class RobotsAlert(T3Alert):
    """Alert for robots.txt drift."""
    
    def __init__(self, source: str, severity: str = "warn", **kwargs):
        super().__init__(
            kind="robots_txt_drifted",
            league_id=None,
            severity=severity,
            message=f"robots.txt changed for {source}",
            metadata={"source": source, **kwargs}
        )
