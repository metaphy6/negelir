"""
Negelir P2P — Reputation system.
Per roadmap §5.3.3: local reputation tables, outcome-based, Sybil-resistant.
"""

from dataclasses import dataclass, field
from node.peer import PeerNode, get_p2p_logger

log = get_p2p_logger("reputation")


@dataclass
class NetworkReputationSummary:
    """Aggregated reputation stats across the network."""
    total_nodes: int = 0
    avg_accuracy: float = 0.0
    leader_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    new_count: int = 0


def compute_network_summary(nodes: list[PeerNode]) -> NetworkReputationSummary:
    """Compute reputation summary across all nodes' local tables."""
    summary = NetworkReputationSummary(total_nodes=len(nodes))

    all_accuracies = []
    trust_counts = {"new": 0, "low": 0, "medium": 0, "high": 0, "leader": 0}

    for node in nodes:
        for peer_id, rep in node.reputation_table.items():
            all_accuracies.append(rep.accuracy_rolling_50)
            trust_counts[rep.trust_level] = trust_counts.get(rep.trust_level, 0) + 1

    summary.avg_accuracy = sum(all_accuracies) / max(1, len(all_accuracies))
    summary.leader_count = trust_counts.get("leader", 0)
    summary.high_count = trust_counts.get("high", 0)
    summary.medium_count = trust_counts.get("medium", 0)
    summary.low_count = trust_counts.get("low", 0)
    summary.new_count = trust_counts.get("new", 0)

    return summary


def print_reputation_matrix(nodes: list[PeerNode]):
    """Print a matrix of how each node views every other node's reputation."""
    from rich.table import Table
    from rich.console import Console

    console = Console(force_terminal=True)
    table = Table(title="🏆 Node Reputation Matrix", show_lines=True)

    table.add_column("Observer", style="cyan")
    for node in nodes:
        table.add_column(node.node_id[:8], justify="center")

    for observer in nodes:
        row = [observer.node_id[:8]]
        for target in nodes:
            if target.node_id == observer.node_id:
                row.append("—")
            else:
                rep = observer.reputation_table.get(target.node_id)
                if rep:
                    emoji = {"new": "🆕", "low": "🔴", "medium": "🟡", "high": "🟢", "leader": "⭐"}.get(rep.trust_level, "❓")
                    row.append(f"{emoji} {rep.accuracy_rolling_50:.0%}")
                else:
                    row.append("❓")
        table.add_row(*row)

    console.print(table)
