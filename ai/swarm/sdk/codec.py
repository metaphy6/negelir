"""Codec seam: the bus is encoding-agnostic.

Phase 3 ships `JsonCodec` only. A CBOR codec can be added in Phase 9 without
touching agents — same `encode` / `decode` shape.
"""
from __future__ import annotations

import json
from typing import Protocol

from .types import Envelope, Message, Topic


class Codec(Protocol):
    """Wire-format codec for bus messages."""

    name: str

    def encode(self, msg: Message) -> bytes: ...
    def decode(self, raw: bytes) -> Message: ...


class JsonCodec:
    """Default codec: UTF-8 JSON with `{envelope, payload}` shape.

    Why a class, not a module: enables a future `CborCodec` to slot in
    without changing call sites.
    """

    name = "json"

    def encode(self, msg: Message) -> bytes:
        body = {"envelope": msg.envelope.as_dict(), "payload": msg.payload}
        return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def decode(self, raw: bytes) -> Message:
        body = json.loads(raw.decode("utf-8"))
        env = Envelope.from_dict(body.get("envelope") or {})
        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError(f"payload must be a JSON object, got {type(payload).__name__}")
        # If the wire envelope omitted topic, fall back to attempt-recovery.
        if not env.topic:
            env = Envelope(
                message_id=env.message_id,
                trace_id=env.trace_id,
                topic=Topic(""),
                producer=env.producer,
                created_at=env.created_at,
                schema_version=env.schema_version,
                attempt=env.attempt,
            )
        return Message(envelope=env, payload=payload)
