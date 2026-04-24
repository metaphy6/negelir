"""Agent base contract.

An `Agent` is a callable bundle of (name, subscribed topics, published
topics, handler). The handler is sync — async is intentionally deferred
until we have a real reason to need it (Phase 11 GPU work).

Idempotency note: per the bus contract, the same `(trace_id, topic)` may
be re-delivered. Handlers must produce the same observable effect on a
re-run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from .types import Message, Topic


@dataclass(frozen=True)
class AgentSpec:
    """Static description of an agent — the only thing the registry stores."""

    name: str
    instance_id: str
    subscribes: tuple[Topic, ...]
    publishes: tuple[Topic, ...]
    pid: int = 0
    started_at: str = ""
    metadata: dict = field(default_factory=dict)


class Agent(Protocol):
    """Minimal contract every bus-driven agent implements."""

    name: str
    subscribes: list[Topic]
    publishes: list[Topic]

    def handle(self, msg: Message) -> Iterable[Message]:
        """Process one inbound message. Return zero or more outbound messages."""
        ...


@dataclass
class FunctionAgent:
    """Convenience adapter: wrap a plain function as an Agent.

    Useful for tests, examples, and one-off scripts where building a class
    is overkill.
    """

    name: str
    subscribes: list[Topic]
    publishes: list[Topic]
    fn: Callable[[Message], Iterable[Message]]

    def handle(self, msg: Message) -> Iterable[Message]:
        return self.fn(msg)
