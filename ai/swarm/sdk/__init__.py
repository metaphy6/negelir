"""
Negelir swarm SDK (Phase 3).

Public surface for building bus-driven agents. The package layout mirrors the
post-Pivot-v3 (Phase R2) target home `common/bus/`; the move is a `git mv` away.

Doctrine:
  - At-least-once delivery; handlers MUST be idempotent.
  - JSON envelopes (CBOR upgrade is purely additive via the `Codec` seam).
  - InMemoryBus and RedisStreamsBus share the same `Bus` interface; tests
    default to InMemoryBus.

Public exports:
  Agent, AgentSpec, Message, Envelope, Topic, Bus, InMemoryBus,
  RedisStreamsBus, JsonCodec, Codec, AgentRegistry, AgentRunner, Metrics.
"""
from __future__ import annotations

from .agent import Agent, AgentSpec
from .bus import Bus, InMemoryBus, RedisStreamsBus
from .codec import Codec, JsonCodec
from .dedup import RequestIdDeduper
from .metrics import Metrics
from .registry import AgentRegistry
from .runner import AgentRunner
from .types import Envelope, Message, Topic

__all__ = [
    "Agent",
    "AgentRegistry",
    "AgentRunner",
    "AgentSpec",
    "Bus",
    "Codec",
    "Envelope",
    "InMemoryBus",
    "JsonCodec",
    "Message",
    "Metrics",
    "RedisStreamsBus",
    "RequestIdDeduper",
    "Topic",
]
