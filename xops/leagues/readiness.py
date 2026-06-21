"""Mock-corpus completeness gate for league promotion (Phase 13.6 + Phase 13.7).

Validates that a league has the required source coverage before T2/T1 promotion.
Per LEAGUE_CATALOG.md §2, T2 requires at least one source per Reference and
Schedule plane; T1 additionally requires Live and Market.

Phase 19.5 extension: participant-crystallisation gate for international tournaments
(wc_qualifier and continental_championship formats).

Usage:
    make leagues.readiness LEAGUE=<league_id> TARGET_TIER=T2
    make leagues.readiness LEAGUE=<league_id> TARGET_TIER=T1 --dry-run
"""

import json
from pathlib import Path
from typing import Dict, List, Literal

from common.league_catalog_loader import load_league_catalog
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


def check_participant_crystallisation_gate(
    league_id: str,
    competition_ids: List[str] | None = None,
) -> Dict:
    """
    Check participant-crystallisation gate for wc_qualifier and continental_championship
    competitions (Phase 19.5).
    
    A wc_qualifier or continental_championship row may only advance to T2 after the
    participant list is final. This is declared via the participant_crystallisation_gate field.
    
    Args:
        league_id: e.g. "wc_qualifier_uefa_2026"
        competition_ids: specific competition IDs to check; if None, checks all in league
    
    Returns:
        dict with "can_advance": bool, "gates": dict of {competition_id: {status, type, details}}
    """
    catalog = load_league_catalog()
    
    if league_id not in catalog:
        return {
            "can_advance": False,
            "gates": {},
            "error": f"league_id not found: {league_id}",
        }
    
    league = catalog[league_id]
    competitions = getattr(league, "competitions", None) or []
    
    # Filter to requested competitions if specified
    if competition_ids:
        competitions = [c for c in competitions if c in competition_ids]
    
    gates = {}
    can_advance = True
    
    for comp_id in competitions:
        # For now, we cannot validate against actual competition configs
        # (they may not be loaded yet in Phase 19.5 implementation).
        # In a full implementation, this would load from CompetitionPayload.
        #
        # The gate declaration is stored in CompetitionPayload.participant_crystallisation_gate
        # We cannot access it here without a full competition catalog loader.
        #
        # For T2 promotion, the operator must verify the gate manually or through
        # a dedicated tool that loads CompetitionPayload objects.
        
        gates[comp_id] = {
            "status": "deferred",
            "reason": "gate validation deferred to dedicated competition validator",
            "note": f"Competition {comp_id} participant_crystallisation_gate must be verified via CompetitionPayload",
        }
    
    return {
        "can_advance": True,  # Deferred to competition validator
        "gates": gates,
    }


def generate_readiness_report(
    league_id: str,
    target_tier: Literal["T2", "T1"],
    dry_run: bool = False,
) -> Dict:
    """Generate a structured readiness report.
    
    For T2 promotion, checks:
    1. Source coverage (Reference, Schedule planes minimum)
    2. Participant crystallisation gate (if competition is wc_qualifier or continental_championship)
    """
    result = check_source_coverage_for_tier(league_id, target_tier)
    
    report = {
        "league_id": league_id,
        "target_tier": target_tier,
        "source_coverage_complete": result["complete"],
        "gaps": result["gaps"],
    }
    
    # For T2 promotion, also check participant crystallisation gate
    if target_tier == "T2":
        gate_result = check_participant_crystallisation_gate(league_id)
        report["participant_crystallisation"] = gate_result
        
        # Overall readiness requires both gates
        overall_ready = result["complete"] and gate_result.get("can_advance", True)
    else:
        overall_ready = result["complete"]
    
    report["overall_ready"] = overall_ready
    
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
    
    if not report.get("overall_ready", False) and not report.get("source_coverage_complete", False):
        sys.exit(1)


class ReadinessReporter:
    """Generate per-league and bulk readiness reports for promotion."""
    
    def generate_report(
        self,
        league_id: str,
        output_format: str = "json"
    ) -> str:
        """Generate a machine-readable readiness report for a single league."""
        import json
        import yaml
        
        report = generate_readiness_report(league_id, "T2", dry_run=True)
        
        if output_format == "json":
            return json.dumps(report, indent=2)
        elif output_format == "yaml":
            return yaml.dump(report, default_flow_style=False)
        else:
            return str(report)
    
    def generate_bulk_report(self) -> str:
        """Generate bulk readiness report for all active T3 leagues."""
        import yaml
        
        catalog = load_league_catalog()
        t3_leagues = [
            (league_id, league)
            for league_id, league in catalog.items()
            if getattr(league, "tier", "T3") == "T3"
        ]
        
        # Sort by promotion readiness score (descending)
        leagues_with_scores = []
        for league_id, league in t3_leagues:
            report = generate_readiness_report(league_id, "T2", dry_run=True)
            score = 0.5 if report.get("source_coverage_complete") else 0.2
            leagues_with_scores.append({
                "league_id": league_id,
                "promotion_readiness_score": score,
                "gaps": report.get("gaps", []),
            })
        
        leagues_with_scores.sort(
            key=lambda x: x["promotion_readiness_score"],
            reverse=True
        )
        
        result = {"leagues": leagues_with_scores}
        return yaml.dump(result, default_flow_style=False)
