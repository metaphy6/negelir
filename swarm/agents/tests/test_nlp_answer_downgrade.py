"""Regression tests for QA answer schema downgrade behavior and downgrade events."""

from __future__ import annotations

import hashlib

from swarm.agents.nlp import (
    _make_qa_answer_payload,
    _unwrap_qa_answer_downgrade_events,
    downgrade_qa_answer_v1,
)
from swarm.sdk.types import Message


def test_qa_answer_downgrade_v3_to_v1_strips_signature_and_collapses_parts() -> None:
    payload = _make_qa_answer_payload(
        request_id="r-1",
        qa_correlation_id="corr-1",
        intent="predict.match_outcome",
        kind="predict.match_outcome",
        answer_text="Galatasaray kazanır.",
        schema_version=3,
        request_metadata={"qa_answer_schema_version": "1", "client_id": "client-1"},
        emitted_at_utc="2026-06-01T00:00:00Z",
    )

    assert payload["schema_version"] == 1
    assert "envelope_signature" not in payload
    assert "parts" not in payload
    assert payload["answer_text"] == "Galatasaray kazanır."

    event = payload.get("_qa_answer_downgrade_event")
    assert isinstance(event, dict)
    assert event["kind"] == "qa_answer_downgraded"
    assert event["from"] == 3
    assert event["to"] == 1
    assert event["client_id_h"] == hashlib.sha256(b"client-1").hexdigest()
    assert isinstance(event["sha_envelope"], str)
    assert len(event["sha_envelope"]) == 64


def test_qa_answer_downgrade_v3_to_v2_keeps_parts_strips_signature() -> None:
    payload = _make_qa_answer_payload(
        request_id="r-2",
        qa_correlation_id="corr-2",
        intent="predict.match_outcome",
        kind="predict.match_outcome",
        answer_text="Beşiktaş önde.",
        schema_version=3,
        request_metadata={"qa_answer_schema_version": 2},
        emitted_at_utc="2026-06-01T00:00:00Z",
    )

    assert payload["schema_version"] == 2
    assert isinstance(payload.get("parts"), list)
    assert "envelope_signature" not in payload
    event = payload.get("_qa_answer_downgrade_event")
    assert isinstance(event, dict)
    assert event["from"] == 3
    assert event["to"] == 2


def test_nlp_qa_answer_downgrade_handler_uses_matrix_only_ast(monkeypatch) -> None:
    payload = _make_qa_answer_payload(
        request_id="r-5",
        qa_correlation_id="corr-5",
        intent="predict.match_outcome",
        kind="predict.match_outcome",
        answer_text="Fenerbahçe önde.",
        schema_version=3,
        request_metadata={"qa_answer_schema_version": 2},
        emitted_at_utc="2026-06-01T00:00:00Z",
    )

    def fake_load_downgrade_matrix() -> dict[str, dict[str, list[str]]]:
        return {
            "3": {"2": ["envelope_signature"], "1": ["envelope_signature"]},
            "2": {"1": []},
        }

    monkeypatch.setattr(
        "swarm.agents.nlp._load_downgrade_matrix",
        fake_load_downgrade_matrix,
    )

    downgraded = downgrade_qa_answer_v1(payload, 2)
    assert downgraded["schema_version"] == 2
    assert "envelope_signature" not in downgraded
    assert "parts" in downgraded


def test_qa_answer_downgrade_v2_to_v1_collapses_parts_only() -> None:
    payload = _make_qa_answer_payload(
        request_id="r-3",
        qa_correlation_id="corr-3",
        intent="predict.match_outcome",
        kind="predict.match_outcome",
        answer_text="Fenerbahçe kazanır.",
        schema_version=2,
        request_metadata={"qa_answer_schema_version": 1},
        emitted_at_utc="2026-06-01T00:00:00Z",
    )

    assert payload["schema_version"] == 1
    assert "parts" not in payload
    assert payload["answer_text"] == "Fenerbahçe kazanır."
    assert isinstance(payload.get("_qa_answer_downgrade_event"), dict)


def test_unwrap_qa_answer_downgrade_events_emits_event_message() -> None:
    payload = _make_qa_answer_payload(
        request_id="r-4",
        qa_correlation_id="corr-4",
        intent="predict.match_outcome",
        kind="predict.match_outcome",
        answer_text="Trabzonspor kazanır.",
        schema_version=3,
        request_metadata={"qa_answer_schema_version": 1},
        emitted_at_utc="2026-06-01T00:00:00Z",
    )
    assert "_qa_answer_downgrade_event" in payload

    msg = Message.new(topic="qa.answer.v1", payload=payload, producer="nlp.answer.v1")
    unfolded = _unwrap_qa_answer_downgrade_events([msg])

    assert len(unfolded) == 2
    assert unfolded[0].topic == "qa.answer.v1"
    assert unfolded[1].topic == "nlp.event.v1"
    assert "_qa_answer_downgrade_event" not in unfolded[0].payload
    assert unfolded[1].payload["kind"] == "qa_answer_downgraded"

