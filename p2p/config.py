"""
Negelir P2P — Centralized environment-driven configuration.
"""

import os
from dataclasses import dataclass, field


@dataclass
class P2PConfig:
    # Shared data / league context
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "/data"))
    default_league_id: str = field(default_factory=lambda: os.getenv("NEGELIR_DEFAULT_LEAGUE_ID", "super_lig"))
    default_league_name: str = field(default_factory=lambda: os.getenv("NEGELIR_DEFAULT_LEAGUE_NAME", "Süper Lig"))
    simulation_min_real_matches: int = field(default_factory=lambda: int(os.getenv("P2P_SIM_MIN_REAL_MATCHES", "10")))

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

    def validate(self, *, strict: bool = False) -> list[str]:
        """
        Range-check P2P configuration. Mirrors ``Config.validate`` semantics:
        returns a list of issue strings, or raises ``ValueError`` when
        ``strict=True`` and any issue is found.
        """
        issues: list[str] = []

        # Ports must fit in the unprivileged TCP/UDP range
        for name, value in (("multicast_port", self.multicast_port), ("tcp_port", self.tcp_port)):
            if not isinstance(value, int) or not (1 <= value <= 65535):
                issues.append(f"{name}={value} outside [1, 65535]")

        # Strict positives
        for name, value in (
            ("message_ttl_hours", self.message_ttl_hours),
            ("data_ttl_hours", self.data_ttl_hours),
            ("discovery_interval_sec", self.discovery_interval_sec),
            ("multicast_ttl", self.multicast_ttl),
            ("tcp_max_message_size", self.tcp_max_message_size),
            ("sim_k_neighbors", self.sim_k_neighbors),
            ("sim_gossip_fanout", self.sim_gossip_fanout),
            ("schema_quorum", self.schema_quorum),
            ("schema_vote_timeout_sec", self.schema_vote_timeout_sec),
            ("simulation_min_real_matches", self.simulation_min_real_matches),
        ):
            if not isinstance(value, int) or value <= 0:
                issues.append(f"{name}={value} must be a positive integer")

        # Timeouts (floats) must be > 0
        for name, value in (
            ("tcp_connect_timeout_sec", self.tcp_connect_timeout_sec),
            ("tcp_read_timeout_sec", self.tcp_read_timeout_sec),
        ):
            if not isinstance(value, (int, float)) or value <= 0:
                issues.append(f"{name}={value} must be > 0")

        # Probability-like fractions must live in [0, 1]
        for name, value in (
            ("sim_drop_rate", self.sim_drop_rate),
            ("schema_confidence_floor", self.schema_confidence_floor),
        ):
            if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
                issues.append(f"{name}={value} outside [0.0, 1.0]")

        # Latency window must be ordered and non-negative
        if self.sim_latency_min_ms < 0 or self.sim_latency_max_ms < 0:
            issues.append(
                f"sim_latency_*_ms must be >= 0 "
                f"(min={self.sim_latency_min_ms}, max={self.sim_latency_max_ms})"
            )
        if self.sim_latency_min_ms > self.sim_latency_max_ms:
            issues.append(
                f"sim_latency_min_ms ({self.sim_latency_min_ms}) > "
                f"sim_latency_max_ms ({self.sim_latency_max_ms})"
            )

        # Required strings
        if not self.data_dir:
            issues.append("data_dir is empty")
        if not self.default_league_id:
            issues.append("default_league_id is empty")

        if strict and issues:
            raise ValueError("P2PConfig validation failed:\n  - " + "\n  - ".join(issues))
        return issues


p2p_cfg = P2PConfig()