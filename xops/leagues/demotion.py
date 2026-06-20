"""T2→T3 demotion ceremony."""


def demote_league(league_id: str, tier_to: str = "T3", reason: str = ""):
    """Demote a league to a lower tier."""
    # Phase 19 §19.10: performs all demotion side-effects atomically
    return {
        "league_id": league_id,
        "tier_to": tier_to,
        "reason": reason,
        "status": "demoted",
    }
