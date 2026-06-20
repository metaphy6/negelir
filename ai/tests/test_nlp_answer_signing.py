"""Tests for Phase 10 §10.26 answer envelope signing and correction grammar."""
from __future__ import annotations

import hashlib

from ai.common.config import cfg
from ai.swarm.sdk import schemas as bus_schemas
from ai.swarm.agents.nlp import (
    _canonical_answer_body,
    _compute_qa_answer_envelope_signature,
    _detect_conversation_correction,
    _load_qa_answer_hmac_keys,
    _load_correction_markers,
    _make_conversation_correction_applied_event,
    _make_conversation_restarted_by_user_event,
    _make_qa_answer_payload,
    downgrade_qa_answer_v1,
)
from ai.swarm.sdk.types import Topic


def _minimal_citation() -> dict[str, object]:
    return {
        "kind": "prediction",
        "prediction_id": "pred-001",
        "produced_at_utc": "2026-05-26T10:00:00Z",
        "model_versions": ["predictor@1.2.3"],
        "calibration_version": "1.0.0",
    }


def _minimal_v3_answer() -> dict[str, object]:
    return _make_qa_answer_payload(
        request_id="req-001",
        qa_correlation_id="qa-001",
        intent="predict.match_outcome",
        kind="direct",
        answer_text="Galatasaray yarın kazanacak.",
        citations=[_minimal_citation()],
        schema_version=3,
    )


def test_qa_answer_v1_schema_accepts_v3_envelope_signature():
    from pytest import MonkeyPatch

    patch = MonkeyPatch()
    try:
        patch.setattr(cfg, "profile", "mock")
        patch.setattr(cfg, "qa_answer_hmac_key_path", "")
        payload = _minimal_v3_answer()
        errors = bus_schemas.validate("qa.answer.v1", payload)
        assert errors == [], f"qa.answer.v1 validation failed: {errors}"
        assert payload["schema_version"] == 3
        assert payload["body_canonical_sha"] == hashlib.sha256(
            _canonical_answer_body(payload).encode("utf-8")
        ).hexdigest()
        assert payload["envelope_signature_key_id"] in _load_qa_answer_hmac_keys()
        expected_signature = _compute_qa_answer_envelope_signature(
            payload,
            _load_qa_answer_hmac_keys()[payload["envelope_signature_key_id"]],
        )
        assert payload["envelope_signature"] == expected_signature
    finally:
        patch.undo()


def test_qa_answer_v1_schema_accepts_request_metadata():
    payload = _minimal_v3_answer()
    payload["request_metadata"] = {
        "input_source": "paste",
        "keyboard_hint": "q",
        "stripped_tail": "source: twitter",
    }
    errors = bus_schemas.validate("qa.answer.v1", payload)
    assert errors == [], f"qa.answer.v1 validation failed: {errors}"


def test_enforce_qa_answer_envelope_hmac_fails_without_keys(monkeypatch):
    monkeypatch.setattr(cfg, "nlp_answer_envelope_hmac_required", "enforce")
    monkeypatch.setattr(
        "swarm.agents.nlp._load_qa_answer_hmac_keys",
        lambda: {},
    )

    from pytest import raises

    with raises(RuntimeError, match="QA answer envelope HMAC is required"):
        _minimal_v3_answer()


def test_downgrade_qa_answer_v1_strips_signature_for_v3_to_v2():
    payload = _minimal_v3_answer()
    downgraded = downgrade_qa_answer_v1(payload, 2)

    assert downgraded["schema_version"] == 2
    assert "envelope_signature" not in downgraded
    assert "envelope_signature_key_id" not in downgraded
    assert "body_canonical_sha" not in downgraded
    assert "parts" in downgraded


def test_downgrade_qa_answer_v1_collapses_parts_for_v3_to_v1():
    payload = _minimal_v3_answer()
    downgraded = downgrade_qa_answer_v1(payload, 1)

    assert downgraded["schema_version"] == 1
    assert "parts" not in downgraded
    assert "envelope_signature" not in downgraded
    assert "envelope_signature_key_id" not in downgraded
    assert "body_canonical_sha" not in downgraded
    assert downgraded["answer_text"] == "Galatasaray yarın kazanacak."


def test_downgrade_qa_answer_v1_uses_matrix_only(monkeypatch):
    payload = _minimal_v3_answer()

    def fake_load_downgrade_matrix() -> dict[str, dict[str, list[str]]]:
        return {
            "3": {
                "2": ["body_canonical_sha"],
                "1": ["envelope_signature"],
            },
            "2": {"1": []},
        }

    monkeypatch.setattr(
        "swarm.agents.nlp._load_downgrade_matrix",
        fake_load_downgrade_matrix,
    )

    downgraded = downgrade_qa_answer_v1(payload, 2)
    assert downgraded["schema_version"] == 2
    assert "body_canonical_sha" not in downgraded
    assert "parts" in downgraded


def test_make_qa_answer_payload_respects_requested_schema_version():
    payload = _make_qa_answer_payload(
        request_id="req-002",
        qa_correlation_id="qa-002",
        intent="predict.match_outcome",
        kind="prediction",
        answer_text="Galatasaray yarın kazanacak.",
        request_metadata={"qa_answer_schema_version": 2},
    )

    assert payload["schema_version"] == 2
    assert "envelope_signature" not in payload
    assert "envelope_signature_key_id" not in payload
    assert "body_canonical_sha" not in payload
    assert "parts" in payload


def test_load_correction_markers_from_closed_table():
    markers = _load_correction_markers()
    assert isinstance(markers, dict)
    assert "replacement" in markers
    assert any("değil" in marker for marker in markers["replacement"])


def test_detect_conversation_correction_replacement_and_restart(monkeypatch):
    monkeypatch.setattr(
        "swarm.agents.nlp._load_correction_markers",
        lambda: {
            "replacement": ["değil", "yerine", "aslında"],
            "restart": ["yok yok", "baştan", "unut onu"],
            "negation_of_prior": ["yok öyle değil", "hayır onu demedim"],
        },
    )

    current_entities = [{"canonical_id": "team_1", "kind": "team"}]
    previous_entities = [{"canonical_id": "team_2", "kind": "team"}]

    normalized_replace = "değil, beşiktaş demek istedim"
    assert _detect_conversation_correction(normalized_replace, current_entities, previous_entities) == "replacement"

    normalized_restart = "yok yok, baştan"
    assert _detect_conversation_correction(normalized_restart, current_entities, previous_entities) == "restart"


def test_make_conversation_correction_events():
    applied = _make_conversation_correction_applied_event(
        request_id="req-002",
        conversation_id="conv-123",
        correction_kind="replacement",
        prior_entity_sha8="abcd1234",
        new_entity_sha8="dcba4321",
    )
    assert applied.topic == Topic("nlp.event.v1")
    assert applied.payload["kind"] == "conversation_correction_applied"
    assert applied.payload["producer"] == "nlp.dispatcher.v1"

    restarted = _make_conversation_restarted_by_user_event(
        request_id="req-003",
        conversation_id="conv-456",
    )
    assert restarted.topic == Topic("nlp.event.v1")
    assert restarted.payload["kind"] == "conversation_restarted_by_user"
