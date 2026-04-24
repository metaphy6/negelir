"""Type primitives for the swarm SDK.

`Topic` is a NewType-style alias over `str` for readability; it does not
enforce anything at runtime.

`Envelope` is the per-message metadata that wraps every payload. The wire
format is `{"envelope": {...}, "payload": {...}}`. The envelope is what
makes at-least-once + retry-budget + schema-versioning work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, NewType
from uuid import uuid4

Topic = NewType("Topic", str)

# Bumping this MUST be paired with a migration plan. Consumers refuse anything
# above their max-supported version.
ENVELOPE_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


@dataclass(frozen=True)
class Envelope:
    """Per-message metadata; wraps every payload on the wire."""

    message_id: str = field(default_factory=_new_id)
    trace_id: str = field(default_factory=_new_id)
    topic: Topic = field(default_factory=lambda: Topic(""))
    producer: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    schema_version: int = ENVELOPE_SCHEMA_VERSION
    attempt: int = 0  # 0 on first publish; runner increments on retry

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        # Defensive copy so callers can mutate `data` after construction.
        return cls(
            message_id=str(data.get("message_id") or _new_id()),
            trace_id=str(data.get("trace_id") or _new_id()),
            topic=Topic(str(data.get("topic", ""))),
            producer=str(data.get("producer", "")),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            schema_version=int(data.get("schema_version", ENVELOPE_SCHEMA_VERSION)),
            attempt=int(data.get("attempt", 0)),
        )


@dataclass(frozen=True)
class Message:
    """A bus message: envelope + payload.

    `payload` must be JSON-serializable. Use a dict; nested primitives only.
    """

    envelope: Envelope
    payload: dict[str, Any]

    @classmethod
    def new(
        cls,
        topic: Topic | str,
        payload: dict[str, Any],
        producer: str = "",
        trace_id: str | None = None,
    ) -> "Message":
        env = Envelope(
            topic=Topic(str(topic)),
            producer=producer,
            trace_id=trace_id or _new_id(),
        )
        return cls(envelope=env, payload=payload)

    def with_envelope(self, envelope: Envelope) -> "Message":
        return Message(envelope=envelope, payload=self.payload)
