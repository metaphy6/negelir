"""
Negelir P2P — In-process transport for simulation.
Uses asyncio queues to simulate TCP transport between nodes.
Can be upgraded to real TCP sockets for production.
"""

import asyncio
from dataclasses import dataclass, field
from node.peer import get_p2p_logger
from protocol.messages import P2PMessage

log = get_p2p_logger("transport")


@dataclass
class SimulatedTransport:
    """
    In-memory message bus for P2P simulation.
    Each node has an inbox (asyncio.Queue) and the transport
    routes messages between them.
    """
    node_inboxes: dict[str, asyncio.Queue] = field(default_factory=dict)

    def register_node(self, node_id: str):
        self.node_inboxes[node_id] = asyncio.Queue()
        log.debug(f"📡 Node registered: {node_id[:8]}")

    def unregister_node(self, node_id: str) -> bool:
        """Remove a node from the transport. Returns True if found."""
        if node_id in self.node_inboxes:
            del self.node_inboxes[node_id]
            log.debug(f"📴 Node unregistered: {node_id[:8]}")
            return True
        return False

    def send(self, sender_id: str, target_id: str, message: P2PMessage):
        """Send a message to a specific node."""
        if target_id in self.node_inboxes:
            self.node_inboxes[target_id].put_nowait(message)
        else:
            log.warning(f"⚠️  Target node not found: {target_id[:8]}")

    def broadcast(self, sender_id: str, message: P2PMessage):
        """Broadcast a message to all nodes except sender."""
        for node_id, inbox in self.node_inboxes.items():
            if node_id != sender_id:
                inbox.put_nowait(message)

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
