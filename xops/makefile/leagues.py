"""Dispatcher for league management targets (readiness, promotion, etc).

Phase 13 — League catalog & tier system.
"""

import argparse
import json
import sys
from pathlib import Path

# Add xops to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from xops.leagues.readiness import generate_readiness_report


def cmd_readiness(argv):
    """Check league readiness for tier promotion.
    
    Usage:
        python3 xops/makefile/leagues.py readiness <league_id> <T2|T1> [--dry-run]
    """
    parser = argparse.ArgumentParser(description="League readiness check")
    parser.add_argument("league_id", help="League ID (e.g., tr_super_lig)")
    parser.add_argument("target_tier", choices=["T2", "T1"], help="Target tier")
    parser.add_argument("--dry-run", action="store_true", help="Don't persist report")
    
    args = parser.parse_args(argv)
    
    report = generate_readiness_report(
        args.league_id,
        args.target_tier,
        dry_run=args.dry_run,
    )
    
    print(json.dumps(report, indent=2))
    
    if not report["source_coverage_complete"]:
        print(f"\n❌ {args.league_id} is not ready for {args.target_tier} promotion")
        print(f"   Gaps: {', '.join(report['gaps'])}", file=sys.stderr)
        return 1
    
    print(f"\n✅ {args.league_id} is ready for {args.target_tier} promotion")
    return 0


COMMANDS = {
    "readiness": cmd_readiness,
}


if __name__ == "__main__":
    import _common
    _common.dispatch(COMMANDS, "leagues")
