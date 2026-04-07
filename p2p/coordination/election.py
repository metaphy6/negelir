"""
Negelir P2P — Deterministic role election.
Phase 4: All peers compute the same result independently.
No coordinator required — sort by (trust, uptime, node_id).
"""

from dataclasses import dataclass


@dataclass
class PeerInfo:
    """Minimal peer info needed for election."""
    node_id: str
    trust_weight: float = 0.5
    uptime_hours: float = 0.0


def elect_roles(peers: list[PeerInfo], epoch_day: int) -> dict[str, str | list[str]]:
    """
    Deterministic role assignment — all peers arrive at the same result.

    Ranking: sort by (-trust_weight, -uptime_hours, node_id).
    The epoch_day parameter is included for future rotation but currently
    the ranking is deterministic for a given peer set.

    Returns:
        {
            "scraper_mackolik": "peer_A",
            "scraper_openfootball": "peer_B",
            "scraper_footballdata": "peer_C",
            "validator": ["peer_A", "peer_B", "peer_C"],
            "indexer": "peer_A",
        }
    """
    if not peers:
        return {
            "scraper_mackolik": "",
            "scraper_openfootball": "",
            "scraper_footballdata": "",
            "validator": [],
            "indexer": "",
        }

    ranked = sorted(peers, key=lambda p: (
        -p.trust_weight,
        -p.uptime_hours,
        p.node_id,  # deterministic tie-breaking
    ))

    n = len(ranked)
    return {
        "scraper_mackolik": ranked[0].node_id,
        "scraper_openfootball": ranked[1 % n].node_id,
        "scraper_footballdata": ranked[2 % n].node_id,
        "validator": [p.node_id for p in ranked[:min(3, n)]],
        "indexer": ranked[0].node_id,
    }
