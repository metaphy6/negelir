"""T3 SLO report generation — excludes T3 leagues from T1/T2 calculations."""
from __future__ import annotations
from typing import Optional


class SLOReportGenerator:
    """Generates SLO reports with T3 leagues excluded."""
    
    def _tier_filter(self, tier: str) -> bool:
        """Filter to only T1/T2 tiers."""
        return tier in ("T1", "T2")
    
    def _build_query(self, include_t3: bool = False) -> str:
        """Build SQL query for SLO metrics."""
        if include_t3:
            return "SELECT * FROM predictions WHERE tier IN ('T1', 'T2', 'T3')"
        else:
            return "SELECT * FROM predictions WHERE tier IN ('T1', 'T2')"
    
    def generate_report(self, output_format: str = "text") -> str:
        """Generate SLO report (T3 excluded)."""
        query = self._build_query(include_t3=False)
        # Placeholder: in production this would query the database
        return f"SLO Report (T3 excluded)\nQuery: {query}"
