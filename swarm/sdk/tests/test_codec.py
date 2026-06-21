"""JsonCodec roundtrip + sad-path tests."""
from __future__ import annotations

import pytest

from swarm.sdk.codec import JsonCodec
from swarm.sdk.types import Message


def test_json_codec_roundtrip_preserves_envelope_and_payload() -> None:
    codec = JsonCodec()
    msg = Message.new("echo.in", {"k": 1, "nested": {"a": [1, 2, 3]}}, producer="p")
    raw = codec.encode(msg)
    restored = codec.decode(raw)
    assert restored.envelope == msg.envelope
    assert restored.payload == msg.payload


def test_json_codec_is_deterministic_sort() -> None:
    """Sorted keys → byte-identical encoding for byte-identical content."""
    codec = JsonCodec()
    a = Message.new("t", {"b": 1, "a": 2})
    b = Message.new(
        a.envelope.topic, {"a": 2, "b": 1},
        producer=a.envelope.producer, trace_id=a.envelope.trace_id,
    )
    # Override created_at + message_id to match for an apples-to-apples test.
    b = b.with_envelope(a.envelope)
    assert codec.encode(a) == codec.encode(b)


def test_json_codec_rejects_non_object_payload() -> None:
    codec = JsonCodec()
    raw = b'{"envelope":{"topic":"x"},"payload":"not-an-object"}'
    with pytest.raises(ValueError):
        codec.decode(raw)


def test_json_codec_handles_missing_envelope_field() -> None:
    codec = JsonCodec()
    raw = b'{"payload":{}}'
    msg = codec.decode(raw)
    assert msg.payload == {}
    assert msg.envelope.message_id  # defaulted


def test_json_codec_name_is_json() -> None:
    assert JsonCodec().name == "json"
