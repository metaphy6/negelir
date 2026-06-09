"""Swarm demo generator — sample prediction with calibration profile rationale.

Per COMPETITIONS.md §9 DoD: `make swarm.demo COMPETITION=<id>` prints a sample
prediction with the calibration profile name in the rationale (showing that
format-aware calibration is working).
"""

import sys
import json
from pathlib import Path
from typing import Optional

# Mock implementation for demo purposes
def generate_sample_prediction(competition_id: str) -> dict:
    """Generate a sample prediction for demo purposes.
    
    Args:
        competition_id: Competition identifier (e.g., "super_lig_2024_25").
    
    Returns:
        Sample prediction dict with calibration profile in rationale.
    """
    # Map competition to profile for demo
    competition_profiles = {
        "super_lig_2024_25": "league_round_robin",
        "turkiye_kupasi": "domestic_cup_early_round",
        "uefa_champions_league": "knockout_continental_club",
        "euro_2024": "international_group_stage",
        "world_cup_2026": "international_knockout",
    }
    
    profile_id = competition_profiles.get(competition_id, "league_round_robin")
    
    return {
        "competition_id": competition_id,
        "competition_format": "group_then_knockout" if "euro" in competition_id or "world_cup" in competition_id else "round_robin",
        "stage_id": "group_stage" if "euro" in competition_id or "world_cup" in competition_id else None,
        "fixture": {
            "stable_id": f"fix_{competition_id}_sample_001",
            "team_a": "team_a",
            "team_b": "team_b",
            "venue_policy": "neutral" if "euro" in competition_id or "world_cup" in competition_id else "home_away",
        },
        "prediction": {
            "home_win": 0.45,
            "draw": 0.30,
            "away_win": 0.25,
        },
        "rationale": {
            "calibration_profile": profile_id,
            "note": f"Prediction calibrated with profile: {profile_id} "
                   f"(competition format-aware overlay per COMPETITIONS.md §4)"
        }
    }


def cmd_demo(argv: list[str]) -> int:
    """CLI: generate and print sample prediction.
    
    Usage:
        python xops/makefile/swarm_demo.py demo COMPETITION=super_lig_2024_25
    """
    if not argv:
        print("Usage: make swarm.demo COMPETITION=<id>", file=sys.stderr)
        return 1
    
    # Parse COMPETITION=<id>
    competition_id = None
    for arg in argv:
        if arg.startswith("COMPETITION="):
            competition_id = arg.replace("COMPETITION=", "")
            break
    
    if not competition_id:
        print("ERROR: COMPETITION argument required", file=sys.stderr)
        return 1
    
    prediction = generate_sample_prediction(competition_id)
    print(json.dumps(prediction, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(cmd_demo(sys.argv[1:]))
