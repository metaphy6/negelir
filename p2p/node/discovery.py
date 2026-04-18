"""
Negelir P2P — Peer discovery (LAN + WAN).
Phase 9: Find peers on local network via UDP multicast
and on the internet via configurable seed nodes.
"""

import asyncio
import json
import socket
import struct
import time
from dataclasses import dataclass, field

from config import p2p_cfg
from node.peer import get_p2p_logger

log = get_p2p_logger("discovery")

# LAN multicast group + port
MULTICAST_GROUP = p2p_cfg.multicast_group
MULTICAST_PORT = p2p_cfg.multicast_port
DISCOVERY_INTERVAL_SEC = p2p_cfg.discovery_interval_sec
ANNOUNCE_TTL = p2p_cfg.multicast_ttl


@dataclass
class DiscoveredPeer:
    """A peer discovered via LAN or WAN."""
    peer_id: str
    host: str
    port: int
    discovered_via: str  # "lan" | "wan" | "seed"
    last_seen: float = field(default_factory=time.time)


class PeerDiscovery:
    """
    Discovers peers on LAN (UDP multicast) and WAN (seed nodes).

    LAN: Periodic UDP multicast announcements on the local network.
    WAN: Connect to known seed nodes / signal server for NAT traversal.
    """

    def __init__(self, node_id: str, listen_port: int = p2p_cfg.tcp_port,
                 seed_nodes: list[tuple[str, int]] | None = None):
        self.node_id = node_id
        self.listen_port = listen_port
        self.seed_nodes = seed_nodes or []
        self._discovered: dict[str, DiscoveredPeer] = {}
        self._running = False

    @property
    def peers(self) -> list[DiscoveredPeer]:
        """Return all discovered peers."""
        return list(self._discovered.values())

    @property
    def peer_count(self) -> int:
        return len(self._discovered)

    def add_seed_node(self, host: str, port: int):
        """Add a WAN seed node for bootstrap."""
        self.seed_nodes.append((host, port))

    def register_peer(self, peer_id: str, host: str, port: int,
                      via: str = "manual"):
        """Manually register a known peer."""
        if peer_id == self.node_id:
            return
        self._discovered[peer_id] = DiscoveredPeer(
            peer_id=peer_id, host=host, port=port,
            discovered_via=via, last_seen=time.time(),
        )
        log.info(f"Peer registered: {peer_id[:8]} at {host}:{port} via {via}")

    def _build_announce(self) -> bytes:
        """Build a LAN announcement packet."""
        payload = json.dumps({
            "type": "negelir_announce",
            "node_id": self.node_id,
            "port": self.listen_port,
            "ts": time.time(),
        }).encode("utf-8")
        return payload

    def _parse_announce(self, data: bytes, addr: tuple) -> DiscoveredPeer | None:
        """Parse a LAN announcement packet."""
        try:
            msg = json.loads(data.decode("utf-8"))
            if msg.get("type") != "negelir_announce":
                return None
            peer_id = msg["node_id"]
            if peer_id == self.node_id:
                return None  # ignore our own announcements
            port = msg.get("port", p2p_cfg.tcp_port)
            host = addr[0]
            return DiscoveredPeer(
                peer_id=peer_id, host=host, port=port,
                discovered_via="lan", last_seen=time.time(),
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def send_lan_announce(self) -> bool:
        """
        Send a UDP multicast announcement on the local network.
        Returns True if sent successfully.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ANNOUNCE_TTL)
            sock.sendto(self._build_announce(), (MULTICAST_GROUP, MULTICAST_PORT))
            sock.close()
            return True
        except OSError as e:
            log.warning(f"LAN announce failed: {e}")
            return False

    def process_announce(self, data: bytes, addr: tuple) -> DiscoveredPeer | None:
        """
        Process a received announcement. Returns the discovered peer
        or None if invalid/self.
        """
        peer = self._parse_announce(data, addr)
        if peer:
            self._discovered[peer.peer_id] = peer
            log.info(f"LAN peer discovered: {peer.peer_id[:8]} at {peer.host}:{peer.port}")
        return peer

    def query_seed_nodes(self) -> list[DiscoveredPeer]:
        """
        Contact seed nodes to get a list of known peers.
        Seed nodes act as a simple registry/rendezvous point.
        """
        new_peers = []
        for host, port in self.seed_nodes:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((host, port))
                request = json.dumps({
                    "type": "peer_query",
                    "node_id": self.node_id,
                    "port": self.listen_port,
                }).encode("utf-8")
                sock.sendall(struct.pack("!I", len(request)) + request)
                header = sock.recv(4)
                if len(header) == 4:
                    length = struct.unpack("!I", header)[0]
                    if length <= 65536:
                        data = sock.recv(length)
                        peers = json.loads(data.decode("utf-8"))
                        for p in peers:
                            peer = DiscoveredPeer(
                                peer_id=p["node_id"],
                                host=p["host"],
                                port=p["port"],
                                discovered_via="seed",
                            )
                            if peer.peer_id != self.node_id:
                                self._discovered[peer.peer_id] = peer
                                new_peers.append(peer)
                sock.close()
            except (OSError, json.JSONDecodeError, KeyError) as e:
                log.warning(f"Seed query to {host}:{port} failed: {e}")
        return new_peers

    def prune_stale(self, max_age_sec: float = 300.0):
        """Remove peers not seen for longer than max_age_sec."""
        now = time.time()
        stale = [
            pid for pid, peer in self._discovered.items()
            if now - peer.last_seen > max_age_sec
        ]
        for pid in stale:
            del self._discovered[pid]
        if stale:
            log.info(f"Pruned {len(stale)} stale peers")
