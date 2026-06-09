"""Mock-corpus completeness gate for league promotion (Phase 13.6 + Phase 13.7).

Validates that a league has the required source coverage before T2/T1 promotion.
Per LEAGUE_CATALOG.md §2, T2 requires at least one source per Reference and
Schedule plane; T1 additionally requires Live and Market.

Usage:
    make leagues.readiness LEAGUE=<league_id> TARGET_TIER=T2
    make leagues.readiness LEAGUE=<league_id> TARGET_TIER=T1 --dry-run
"""

import json
from pathlib import Path
from typing import Dict, List, Literal

from ai.common.league_catalog_loader import load_league_catalog
from xops.mock.sources import all_keys as get_all_source_keys


def check_source_coverage_for_tier(
    league_id: str,
    target_tier: Literal["T2", "T1"],
) -> Dict[str, List[str]]:
    """
    Validate that league has required source coverage for target tier.
    
    Args:
        league_id: e.g. "tr_super_lig"
        target_tier: "T2" or "T1"
    
    Returns:
        dict with keys "complete" (bool), "gaps" (list of missing planes/sources)
    """
    catalog = load_league_catalog()
    
    if league_id not in catalog:
        return {
            "complete": False,
            "gaps": [f"league_id not found: {league_id}"],
        }
    
    league = catalog[league_id]
    source_coverage = league.source_coverage or {}
    
    if not source_coverage:
        return {
            "complete": False,
            "gaps": ["no source_coverage defined"],
        }
    
    # Required planes per tier
    required_planes = {"reference", "schedule"}
    if target_tier == "T1":
        required_planes.update({"live", "market"})
    
    gaps = []
    valid_sources = set(get_all_source_keys())
    
    for plane in required_planes:
        sources = getattr(source_coverage, plane, None) or []
        
        if not sources:
            gaps.append(f"{plane} plane: no sources")
            continue
        
        # Validate each source exists in registry
        for source in sources:
            if source not in valid_sources:
                gaps.append(f"{plane} plane: unknown source {source!r}")
    
    return {
        "complete": len(gaps) == 0,
        "gaps": gaps,
    }


def generate_readiness_report(
    league_id: str,
    target_tier: Literal["T2", "T1"],
    dry_run: bool = False,
) -> Dict:
    """Generate a structured readiness report."""
    result = check_source_coverage_for_tier(league_id, target_tier)
    
    report = {
        "league_id": league_id,
        "target_tier": target_tier,
        "source_coverage_complete": result["complete"],
        "gaps": result["gaps"],
    }
    
    # Persist report unless dry-run
    if not dry_run:
        report_dir = Path(f"data/leagues/readiness/{league_id}")
        report_dir.mkdir(parents=True, exist_ok=True)
        
        # Write report with timestamp
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        report_file = report_dir / f"{now.replace(':', '-')}.json"
        
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)
    
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: readiness.py <league_id> <T2|T1> [--dry-run]")
        sys.exit(1)
    
    league_id = sys.argv[1]
    target_tier = sys.argv[2]
    dry_run = "--dry-run" in sys.argv
    
    report = generate_readiness_report(league_id, target_tier, dry_run)
    
    print(json.dumps(report, indent=2))
    
    if not report["source_coverage_complete"]:
        sys.exit(1)
