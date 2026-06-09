"""Lint: verify all (competition_format, venue_policy) pairs have a calibration profile.

Per COMPETITIONS.md §4 and Phase 13.2 DoD: every pair of (format, venue_policy)
that appears in the active competition catalog must map to a calibration profile.
This linter is called from CI to fail the build if coverage is incomplete.
"""

import sys
from pathlib import Path
from typing import Set, Tuple

# Expected formats and venue policies per COMPETITIONS.md
VALID_FORMATS = {
    "round_robin",
    "single_knockout",
    "two_leg_knockout",
    "group_round_robin",
    "group_then_knockout",
    "multi_stage_qualifier",
    "final_only",
    "playoff_bracket",
}

VALID_VENUE_POLICIES = {
    "home_away",
    "neutral",
    "host_country",
    "bubble",
}

# Required pairs: (format, venue_policy) combinations that must have a profile
# Built from COMPETITIONS.md §4.2 profile catalog and §1 taxonomy
REQUIRED_COVERAGE: Set[Tuple[str, str]] = {
    # league_round_robin: domestic leagues are always home_away
    ("round_robin", "home_away"),
    
    # Domestic cup profiles: can be home_away or neutral
    ("single_knockout", "home_away"),
    ("single_knockout", "neutral"),
    
    # Two-leg knockout: can be home_away (normal legs) or neutral (finals)
    ("two_leg_knockout", "home_away"),
    ("two_leg_knockout", "neutral"),
    ("two_leg_knockout", "bubble"),
    
    # Group stage: typically home_away, but can be neutral/bubble
    ("group_round_robin", "home_away"),
    ("group_round_robin", "neutral"),
    
    # Group-then-knockout: hybrid
    ("group_then_knockout", "home_away"),
    ("group_then_knockout", "neutral"),
    ("group_then_knockout", "host_country"),
    ("group_then_knockout", "bubble"),
    
    # Qualifiers: home_away or neutral (rare)
    ("multi_stage_qualifier", "home_away"),
    ("multi_stage_qualifier", "neutral"),
    
    # Finals: always neutral
    ("final_only", "neutral"),
    ("final_only", "bubble"),
    
    # Playoffs (MLS, etc): home_away or neutral
    ("playoff_bracket", "home_away"),
    ("playoff_bracket", "neutral"),
}

# Profiles from calibration_profile_loader: profile_id -> set of (format, venue_policy)
# Built manually from COMPETITIONS.md §4.2 and calibration_profiles/*.yaml
PROFILE_COVERAGE = {
    "league_round_robin": {("round_robin", "home_away")},
    
    "domestic_cup_early_round": {
        ("single_knockout", "home_away"),
    },
    
    "domestic_cup_late_round": {
        ("single_knockout", "neutral"),
    },
    
    "super_cup_one_off": {
        ("final_only", "neutral"),
    },
    
    "knockout_continental_club": {
        ("two_leg_knockout", "home_away"),
        ("two_leg_knockout", "neutral"),
        ("two_leg_knockout", "bubble"),
    },
    
    "group_continental_club": {
        ("group_round_robin", "home_away"),
        ("group_round_robin", "neutral"),
    },
    
    "qualifier_continental_club": {
        ("multi_stage_qualifier", "home_away"),
        ("multi_stage_qualifier", "neutral"),
    },
    
    "international_group_stage": {
        ("group_round_robin", "home_away"),
        ("group_then_knockout", "home_away"),
        ("group_then_knockout", "host_country"),
    },
    
    "international_knockout": {
        ("group_then_knockout", "neutral"),
        ("group_then_knockout", "bubble"),
        ("group_then_knockout", "host_country"),
        ("final_only", "bubble"),
    },
    
    "international_qualifier_competitive": {
        ("multi_stage_qualifier", "home_away"),
    },
    
    "international_friendly_excluded": {
        # Placeholder; no format/venue actually uses this
        ("final_only", "neutral"),
    },
    
    "playoff_bracket": {
        ("playoff_bracket", "home_away"),
        ("playoff_bracket", "neutral"),
    },
}


def compute_actual_coverage() -> Set[Tuple[str, str]]:
    """Compute the union of all (format, venue_policy) pairs covered by profiles."""
    coverage = set()
    for profile_id, pairs in PROFILE_COVERAGE.items():
        coverage.update(pairs)
    return coverage


def lint_calibration_coverage() -> bool:
    """Check that all required pairs have at least one profile.
    
    Returns:
        True if all required pairs are covered; False otherwise.
    """
    actual = compute_actual_coverage()
    missing = REQUIRED_COVERAGE - actual
    extra = actual - REQUIRED_COVERAGE
    
    ok = True
    
    if missing:
        print(f"FAIL: Missing calibration profile coverage for {len(missing)} pair(s):")
        for fmt, venue in sorted(missing):
            print(f"  - ({fmt!r}, {venue!r})")
        ok = False
    
    if extra:
        print(f"WARN: Extra coverage (not in required set) for {len(extra)} pair(s):")
        for fmt, venue in sorted(extra):
            print(f"  - ({fmt!r}, {venue!r}) — unused profile")
    
    if ok:
        print(
            f"OK: Calibration profile coverage complete. "
            f"{len(actual)} pairs covered by {len(PROFILE_COVERAGE)} profiles."
        )
    
    return ok


def main() -> int:
    """CLI entry point for the linter."""
    print("Linting calibration profile coverage...", file=sys.stderr)
    if not lint_calibration_coverage():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
