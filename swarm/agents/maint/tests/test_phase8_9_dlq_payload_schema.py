"""Phase 8 §8.9 DoD — DLQ payload-vs-schema discipline.

Proves:
1. For schemas with ``additionalProperties:false``, :func:`dlq_meta_policy`
   returns ``"out_of_band"`` and the supervisor's ``_dlq_meta_policy``
   strips the ``.dlq`` suffix correctly.
2. For opt-in (permissive) schemas, ``dlq_meta_policy`` returns
   ``"inject"``.
3. Payload schema validation passes BOTH ways:
   - Strict topic payload validates WITHOUT ``__dlq_meta`` in the body.
   - Opt-in topic payload validates WITH ``__dlq_meta`` merged in.
"""
from __future__ import annotations

import json
import pathlib

import jsonschema

from swarm.agents.maint.dlq import (
    MaintDlqSupervisor,
    _STRICT_PAYLOAD_TOPICS,
    dlq_meta_policy,
)

_SCHEMAS = pathlib.Path(__file__).parents[4] / "swarm" / "sdk" / "schemas"


def _load(name: str) -> dict:
    return json.loads((_SCHEMAS / name).read_text())


# ── 1. Policy function: strict schema ─────────────────────────────


def test_strict_topic_policy_out_of_band() -> None:
    """predict.vote has additionalProperties:false → out_of_band."""
    assert dlq_meta_policy("predict.vote") == "out_of_band"


def test_strict_topic_freshness_out_of_band() -> None:
    assert dlq_meta_policy("freshness.events.v1") == "out_of_band"


# ── 2. Policy function: opt-in schema ─────────────────────────────


def test_opt_in_topic_policy_inject() -> None:
    """telemetry schema has no additionalProperties:false → inject."""
    assert dlq_meta_policy("telemetry") == "inject"


def test_unknown_topic_policy_inject() -> None:
    """An unknown topic not in _STRICT_PAYLOAD_TOPICS defaults to inject."""
    assert dlq_meta_policy("some.unknown.topic.v99") == "inject"


# ── 3. Supervisor strips .dlq suffix ──────────────────────────────


def test_supervisor_dlq_meta_policy_strips_suffix() -> None:
    sup = MaintDlqSupervisor()
    assert sup._dlq_meta_policy("predict.vote.dlq") == "out_of_band"


def test_supervisor_dlq_meta_policy_opt_in_suffix() -> None:
    sup = MaintDlqSupervisor()
    assert sup._dlq_meta_policy("telemetry.dlq") == "inject"


def test_supervisor_dlq_meta_policy_no_suffix() -> None:
    """Topic without .dlq suffix is treated as the origin topic itself."""
    sup = MaintDlqSupervisor()
    assert sup._dlq_meta_policy("predict.vote") == "out_of_band"


# ── 4. Payload schema validation: strict (no __dlq_meta) ──────────


def test_strict_payload_validates_without_dlq_meta() -> None:
    """A valid predict.vote payload WITHOUT __dlq_meta passes strict schema."""
    schema = _load("predict.vote.json")
    payload = {
        "request_id": "req-001",
        "match_id": "match-42",
        "market": "1x2",
        "predictor_id": "pred.v1",
        "distribution": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "confidence": 0.87,
    }
    # Must not raise
    jsonschema.validate(instance=payload, schema=schema)


def test_strict_payload_fails_with_dlq_meta_injected() -> None:
    """Injecting __dlq_meta into a strict payload violates the schema."""
    schema = _load("predict.vote.json")
    payload = {
        "request_id": "req-001",
        "match_id": "match-42",
        "market": "1x2",
        "predictor_id": "pred.v1",
        "distribution": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "confidence": 0.87,
        "__dlq_meta": {"retry": 1, "source_dlq": "predict.vote.dlq"},
    }
    try:
        jsonschema.validate(instance=payload, schema=schema)
        assert False, "Expected ValidationError for __dlq_meta in strict schema"
    except jsonschema.ValidationError:
        pass


# ── 5. Payload schema validation: opt-in (with __dlq_meta) ────────


def test_opt_in_payload_validates_with_dlq_meta() -> None:
    """A telemetry payload WITH __dlq_meta passes the permissive schema."""
    schema = _load("telemetry.json")
    payload = {
        "kind": "replay.started",
        "emitted_at": "2025-01-01T00:00:00+00:00",
        "__dlq_meta": {"retry": 1, "source_dlq": "telemetry.dlq"},
    }
    # Must not raise — schema is permissive (additionalProperties not false)
    jsonschema.validate(instance=payload, schema=schema)


# ── 6. _STRICT_PAYLOAD_TOPICS set round-trips with actual schemas ──


def test_strict_payload_topics_matches_schema_files() -> None:
    """Every topic in _STRICT_PAYLOAD_TOPICS has a matching schema file
    with additionalProperties:false.  This test catches schema drift."""
    topic_to_file = {
        "freshness.events.v1": "freshness.events.v1.json",
        "maint.ack.v1": "maint.ack.v1.json",
        "match.normalized": "match.normalized.json",
        "match.outcome.v1": "match.outcome.v1.json",
        "match.stored": "match.stored.json",
        "predict.final": "predict.final.json",
        "predict.request": "predict.request.json",
        "predict.vote": "predict.vote.json",
        "sec.alert.v1": "sec.alert.v1.json",
        "sec.quarantine.v1": "sec.quarantine.v1.json",
    }
    for topic, filename in topic_to_file.items():
        schema = _load(filename)
        assert schema.get("additionalProperties") is False, (
            f"Topic '{topic}' is in _STRICT_PAYLOAD_TOPICS but "
            f"'{filename}' does not declare additionalProperties:false"
        )
        assert topic in _STRICT_PAYLOAD_TOPICS, (
            f"Schema '{filename}' has additionalProperties:false but "
            f"topic '{topic}' is missing from _STRICT_PAYLOAD_TOPICS"
        )
