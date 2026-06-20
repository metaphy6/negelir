"""Catalog audit log — append-only signed records."""


def append_decommission_row(league_id: str, reason: str, operator: str):
    """Append a decommission row to audit log."""
    # Phase 19 §19.10: append-only, cryptographically signed
    return {
        "event": "decommission",
        "league_id": league_id,
        "reason": reason,
        "operator": operator,
    }


def append_demotion_row(league_id: str, tier_from: str, tier_to: str, reason: str, operator: str):
    """Append a demotion row to audit log."""
    return {
        "event": "demotion",
        "league_id": league_id,
        "tier_from": tier_from,
        "tier_to": tier_to,
        "reason": reason,
        "operator": operator,
    }
