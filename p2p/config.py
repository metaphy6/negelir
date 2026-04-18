"""
Negelir P2P — Centralized environment-driven configuration.
"""

import os
from dataclasses import dataclass, field


@dataclass
class P2PConfig:
    # Message + retention
    message_ttl_hours: int = field(default_factory=lambda: int(os.getenv("P2P_MESSAGE_TTL_HOURS", "168")))
    data_ttl_hours: int = field(default_factory=lambda: int(os.getenv("P2P_DATA_TTL_HOURS", "168")))

    # Discovery
    multicast_group: str = field(default_factory=lambda: os.getenv("P2P_MULTICAST_GROUP", "239.42.42.1"))
    multicast_port: int = field(default_factory=lambda: int(os.getenv("P2P_MULTICAST_PORT", "9743")))
    discovery_interval_sec: int = field(default_factory=lambda: int(os.getenv("P2P_DISCOVERY_INTERVAL_SEC", "30")))
    multicast_ttl: int = field(default_factory=lambda: int(os.getenv("P2P_MULTICAST_TTL", "2")))

    # TCP transport
    tcp_host: str = field(default_factory=lambda: os.getenv("P2P_TCP_HOST", "0.0.0.0"))
    tcp_port: int = field(default_factory=lambda: int(os.getenv("P2P_TCP_PORT", "9742")))
    tcp_connect_timeout_sec: float = field(default_factory=lambda: float(os.getenv("P2P_TCP_CONNECT_TIMEOUT_SEC", "5.0")))
    tcp_read_timeout_sec: float = field(default_factory=lambda: float(os.getenv("P2P_TCP_READ_TIMEOUT_SEC", "10.0")))
    tcp_max_message_size: int = field(default_factory=lambda: int(os.getenv("P2P_TCP_MAX_MESSAGE_SIZE", str(1024 * 1024))))

    # Simulated transport realism
    sim_latency_min_ms: float = field(default_factory=lambda: float(os.getenv("P2P_SIM_LATENCY_MIN_MS", "20.0")))
    sim_latency_max_ms: float = field(default_factory=lambda: float(os.getenv("P2P_SIM_LATENCY_MAX_MS", "150.0")))
    sim_drop_rate: float = field(default_factory=lambda: float(os.getenv("P2P_SIM_DROP_RATE", "0.02")))
    sim_k_neighbors: int = field(default_factory=lambda: int(os.getenv("P2P_SIM_K_NEIGHBORS", "8")))
    sim_gossip_fanout: int = field(default_factory=lambda: int(os.getenv("P2P_SIM_GOSSIP_FANOUT", "3")))

    # Schema gossip consensus
    schema_quorum: int = field(default_factory=lambda: int(os.getenv("P2P_SCHEMA_QUORUM", "3")))
    schema_vote_timeout_sec: int = field(default_factory=lambda: int(os.getenv("P2P_SCHEMA_VOTE_TIMEOUT_SEC", "600")))
    schema_confidence_floor: float = field(default_factory=lambda: float(os.getenv("P2P_SCHEMA_CONFIDENCE_FLOOR", "0.6")))


p2p_cfg = P2PConfig()