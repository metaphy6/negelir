"""
Negelir P2P — Message protocol types.
Per roadmap §7.3: schema-versioned messages with signatures.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum


class MessageType(Enum):
    ANALYSIS = "analysis"
    OUTCOME_VALIDATION = "outcome_validation"
    SCRAPE_DATA = "scrape_data"
    PEER_DISCOVERY = "peer_discovery"
    PING = "ping"
    PONG = "pong"


@dataclass
class P2PMessage:
    """Base P2P message per roadmap §7.3."""
    schema_version: str = "2.0"
    message_type: str = ""
    sender_id: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl_hours: int = 168  # 7 days

    @property
    def content_hash(self) -> str:
        data = json.dumps({
            "type": self.message_type,
            "sender": self.sender_id,
            "payload": self.payload,
            "ts": self.timestamp,
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    def to_bytes(self) -> bytes:
        return json.dumps({
            "schema_version": self.schema_version,
            "message_type": self.message_type,
            "sender_id": self.sender_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "ttl_hours": self.ttl_hours,
            "content_hash": self.content_hash,
        }).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "P2PMessage":
        d = json.loads(data.decode("utf-8"))
        msg = cls(
            schema_version=d.get("schema_version", "2.0"),
            message_type=d.get("message_type", ""),
            sender_id=d.get("sender_id", ""),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", 0),
            ttl_hours=d.get("ttl_hours", 168),
        )
        # Verify content hash
        expected_hash = d.get("content_hash", "")
        if expected_hash and msg.content_hash != expected_hash:
            raise ValueError(f"Content hash mismatch: expected {expected_hash}, got {msg.content_hash}")
        return msg

    def is_expired(self) -> bool:
        age_hours = (time.time() - self.timestamp) / 3600
        return age_hours > self.ttl_hours
