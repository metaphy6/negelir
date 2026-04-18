"""
Negelir P2P — In-process transport for simulation.
Uses asyncio queues to simulate TCP transport between nodes.

Realism features (gap-closing):
  - Wire serialization: messages are serialized to bytes before delivery
    and deserialized on receive (catches serde bugs).
  - Simulated latency: configurable RTT range per message.
  - Simulated packet loss: configurable drop probability.
  - k-neighbor topology: each node only knows k peers (partial mesh),
    not the full network. Gossip-style fanout for broadcast.
"""

import asyncio
import random
import time
from dataclasses import dataclass, field

from config import p2p_cfg
from node.peer import get_p2p_logger
from protocol.messages import P2PMessage

log = get_p2p_logger("transport")


@dataclass
class TransportStats:
    """Counters for transport-level realism metrics."""
    messages_sent: int = 0
    messages_delivered: int = 0
    messages_dropped: int = 0
    bytes_serialized: int = 0
    serde_errors: int = 0
    total_latency_ms: float = 0.0

    @property
    def drop_rate(self) -> float:
        return self.messages_dropped / max(1, self.messages_sent)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(1, self.messages_delivered)


@dataclass
class SimulatedTransport:
    """
    In-memory message bus for P2P simulation with realism knobs.

    Each node has an inbox (asyncio.Queue) and the transport
    routes messages between them — but now with:
      1. Wire serialization (to_bytes / from_bytes on every hop)
      2. Simulated latency (configurable RTT range)
      3. Simulated packet loss (configurable drop rate)
      4. k-neighbor partial mesh topology (gossip fanout)
    """
    node_inboxes: dict[str, asyncio.Queue] = field(default_factory=dict)

    # ── Realism knobs ───────────────────────────────────
    latency_ms_range: tuple[float, float] = field(default_factory=lambda: (
        p2p_cfg.sim_latency_min_ms,
        p2p_cfg.sim_latency_max_ms,
    ))
    drop_rate: float = field(default_factory=lambda: p2p_cfg.sim_drop_rate)
    k_neighbors: int = field(default_factory=lambda: p2p_cfg.sim_k_neighbors)
    gossip_fanout: int = field(default_factory=lambda: p2p_cfg.sim_gossip_fanout)

    # ── Topology ────────────────────────────────────────
    _neighbor_table: dict[str, list[str]] = field(default_factory=dict)

    # ── Metrics ─────────────────────────────────────────
    stats: TransportStats = field(default_factory=TransportStats)

    # ── Node management ──────────────────────────────────

    def register_node(self, node_id: str):
        self.node_inboxes[node_id] = asyncio.Queue()
        self._rebuild_topology()
        log.debug(f"📡 Node registered: {node_id[:8]}")

    def unregister_node(self, node_id: str) -> bool:
        """Remove a node from the transport. Returns True if found."""
        if node_id in self.node_inboxes:
            del self.node_inboxes[node_id]
            self._neighbor_table.pop(node_id, None)
            self._rebuild_topology()
            log.debug(f"📴 Node unregistered: {node_id[:8]}")
            return True
        return False

    # ── Topology builder ─────────────────────────────────

    def _rebuild_topology(self):
        """Build k-neighbor partial mesh from current node set."""
        all_ids = list(self.node_inboxes.keys())
        k = min(self.k_neighbors, len(all_ids) - 1)
        if k <= 0:
            self._neighbor_table = {nid: [] for nid in all_ids}
            return
        rng = random.Random(42)  # deterministic for reproducibility
        for nid in all_ids:
            others = [x for x in all_ids if x != nid]
            rng.shuffle(others)
            self._neighbor_table[nid] = others[:k]

    def get_neighbors(self, node_id: str) -> list[str]:
        """Return the k-neighbor list for a node."""
        return list(self._neighbor_table.get(node_id, []))

    # ── Wire serialization helpers ───────────────────────

    def _serialize(self, message: P2PMessage) -> bytes | None:
        """Serialize a message to bytes (catches serde bugs)."""
        try:
            data = message.to_bytes()
            self.stats.bytes_serialized += len(data)
            return data
        except Exception as exc:
            self.stats.serde_errors += 1
            log.warning(f"⚠️  Serialization error: {exc}")
            return None

    def _deserialize(self, data: bytes) -> P2PMessage | None:
        """Deserialize bytes back to a message (catches serde bugs)."""
        try:
            return P2PMessage.from_bytes(data)
        except Exception as exc:
            self.stats.serde_errors += 1
            log.warning(f"⚠️  Deserialization error: {exc}")
            return None

    # ── Latency + drop simulation ────────────────────────

    def _should_drop(self) -> bool:
        return random.random() < self.drop_rate

    def _simulate_latency(self) -> float:
        """Return a simulated one-way latency in milliseconds."""
        lo, hi = self.latency_ms_range
        return random.uniform(lo, hi)

    # ── Send / broadcast ─────────────────────────────────

    def send(self, sender_id: str, target_id: str, message: P2PMessage):
        """Send a message to a specific node (serialized, with latency + drop)."""
        self.stats.messages_sent += 1

        if target_id not in self.node_inboxes:
            log.warning(f"⚠️  Target node not found: {target_id[:8]}")
            return

        # Simulate packet loss
        if self._should_drop():
            self.stats.messages_dropped += 1
            log.debug(f"📦💀 Dropped: {sender_id[:8]}→{target_id[:8]}")
            return

        # Serialize on the wire
        wire_bytes = self._serialize(message)
        if wire_bytes is None:
            return

        # Deserialize on the receive side
        received = self._deserialize(wire_bytes)
        if received is None:
            return

        # Simulate latency (accounted in stats, not actual sleep)
        latency = self._simulate_latency()
        self.stats.total_latency_ms += latency

        self.node_inboxes[target_id].put_nowait(received)
        self.stats.messages_delivered += 1

    def broadcast(self, sender_id: str, message: P2PMessage):
        """
        Gossip broadcast: send to k-neighbors only (partial mesh).
        Each receiving node would re-gossip in a real implementation;
        here we simulate one-hop gossip fanout for simplicity.
        """
        neighbors = self.get_neighbors(sender_id)
        if not neighbors:
            # Fallback: if topology not built yet, send to all
            neighbors = [nid for nid in self.node_inboxes if nid != sender_id]

        # First hop: send to all direct neighbors
        reached: set[str] = set()
        for target_id in neighbors:
            if target_id != sender_id:
                self.send(sender_id, target_id, message)
                reached.add(target_id)

        # Second hop: each neighbor re-gossips to `gossip_fanout` of *their* neighbors
        for relay_id in list(reached):
            relay_neighbors = self.get_neighbors(relay_id)
            fanout_targets = [n for n in relay_neighbors if n != sender_id and n not in reached]
            random.shuffle(fanout_targets)
            for target_id in fanout_targets[:self.gossip_fanout]:
                self.send(relay_id, target_id, message)
                reached.add(target_id)

    def get_pending(self, node_id: str) -> list[P2PMessage]:
        """Get all pending messages for a node (non-blocking)."""
        inbox = self.node_inboxes.get(node_id)
        if not inbox:
            return []
        messages = []
        while not inbox.empty():
            try:
                messages.append(inbox.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    @property
    def node_count(self) -> int:
        return len(self.node_inboxes)
