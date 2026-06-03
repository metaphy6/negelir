"""Tests for Phase 9 API bus schemas (api.request.v1 and related).

Per AGENTS.md Rule 10: new schema file → happy + adversarial tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.swarm.sdk import schemas as bus_schemas

SCHEMA_DIR = Path(__file__).parent.parent / "swarm" / "sdk" / "schemas"


# ── helpers ──────────────────────────────────────────────────────────────

def _valid_api_request() -> dict:
    """Minimal valid api.request.v1 payload (all required fields only)."""
    return {
        "request_id": "req-abc123",
        "anon_subject_key": "ip:192.0.2.0",
        "route": "/v1/matches/:id",
        "method": "GET",
        "accepted_at": "2026-05-26T10:00:00Z",
    }


# ── api.request.v1 ───────────────────────────────────────────────────────

class TestApiRequestV1Schema:
    TOPIC = "api.request.v1"

    def test_schema_file_exists_and_is_valid_json(self):
        path = SCHEMA_DIR / f"{self.TOPIC}.json"
        assert path.exists(), f"Schema file missing: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("$id") == f"negelir/swarm/{self.TOPIC}"

    def test_schema_has_additional_properties_false(self):
        schema = bus_schemas.load(self.TOPIC)
        assert schema.get("additionalProperties") is False, (
            "api.request.v1 must have additionalProperties=false"
        )

    def test_happy_path_minimal(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_api_request())
        assert errors == [], f"Unexpected errors: {errors}"

    def test_happy_path_all_optional_fields(self):
        payload = {
            **_valid_api_request(),
            "user_id": "user-42",
            "status_anticipated": 429,
            "sec_gate_ms": 1.5,
            "auth_ms": 2.3,
        }
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_happy_path_status_anticipated_null(self):
        payload = {**_valid_api_request(), "status_anticipated": None}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_missing_required_request_id(self):
        payload = _valid_api_request()
        del payload["request_id"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("request_id" in e for e in errors)

    def test_missing_required_anon_subject_key(self):
        payload = _valid_api_request()
        del payload["anon_subject_key"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("anon_subject_key" in e for e in errors)

    def test_missing_required_route(self):
        payload = _valid_api_request()
        del payload["route"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("route" in e for e in errors)

    def test_missing_required_method(self):
        payload = _valid_api_request()
        del payload["method"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("method" in e for e in errors)

    def test_missing_required_accepted_at(self):
        payload = _valid_api_request()
        del payload["accepted_at"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("accepted_at" in e for e in errors)

    def test_invalid_method_enum(self):
        payload = {**_valid_api_request(), "method": "CONNECT"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("method" in e for e in errors)

    def test_additional_property_rejected(self):
        payload = {**_valid_api_request(), "raw_ip": "203.0.113.5"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("raw_ip" in e for e in errors), (
            "api.request.v1 must reject raw_ip (additionalProperties=false); "
            "raw IP must never appear in payloads (§7.6 SubjectKey contract)"
        )

    def test_known_topics_includes_api_request_v1(self):
        assert self.TOPIC in bus_schemas.known_topics(), (
            f"{self.TOPIC} not returned by known_topics()"
        )


# ── nlp.alert.v1 ─────────────────────────────────────────────────────────

def _valid_nlp_alert() -> dict:
    """Minimal valid nlp.alert.v1 payload (all required fields only)."""
    return {
        "alert_id": "alert-nlp-001",
        "kind": "lexicon_unreadable",
        "severity": "error",
        "source": "nlp.intent.v1",
        "reason": "Failed to parse teams.tr.yaml",
        "emitted_at": "2026-05-26T10:00:00Z",
    }


class TestNlpAlertV1Schema:
    TOPIC = "nlp.alert.v1"

    def test_schema_file_exists_and_is_valid_json(self):
        path = SCHEMA_DIR / f"{self.TOPIC}.json"
        assert path.exists(), f"Schema file missing: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("$id") == f"negelir/swarm/{self.TOPIC}"

    def test_schema_has_additional_properties_false(self):
        schema = bus_schemas.load(self.TOPIC)
        assert schema.get("additionalProperties") is False, (
            "nlp.alert.v1 must have additionalProperties=false"
        )

    def test_happy_path_minimal(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_nlp_alert())
        assert errors == [], f"Unexpected errors: {errors}"

    def test_happy_path_all_optional_fields(self):
        payload = {
            **_valid_nlp_alert(),
            "schema_version": 1,
            "subject": "teams.tr.yaml",
            "request_id": "req-42",
            "qa_correlation_id": "qacorr-123",
            "details": {"lexicon_file": "teams.tr.yaml", "entry_count": 5000},
        }
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_happy_path_subject_null(self):
        payload = {**_valid_nlp_alert(), "subject": None}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_happy_path_details_null(self):
        payload = {**_valid_nlp_alert(), "details": None}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_missing_required_alert_id(self):
        payload = _valid_nlp_alert()
        del payload["alert_id"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("alert_id" in e for e in errors)

    def test_missing_required_kind(self):
        payload = _valid_nlp_alert()
        del payload["kind"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("kind" in e for e in errors)

    def test_missing_required_severity(self):
        payload = _valid_nlp_alert()
        del payload["severity"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("severity" in e for e in errors)

    def test_missing_required_source(self):
        payload = _valid_nlp_alert()
        del payload["source"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("source" in e for e in errors)

    def test_missing_required_reason(self):
        payload = _valid_nlp_alert()
        del payload["reason"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("reason" in e for e in errors)

    def test_missing_required_emitted_at(self):
        payload = _valid_nlp_alert()
        del payload["emitted_at"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("emitted_at" in e for e in errors)

    def test_invalid_severity_enum(self):
        payload = {**_valid_nlp_alert(), "severity": "catastrophic"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("severity" in e for e in errors)

    def test_additional_properties_rejected(self):
        payload = {**_valid_nlp_alert(), "extra_field": "should_not_be_here"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("additional" in e.lower() or "extra_field" in e for e in errors)


# ── qa.request.v1 locale enum (§10.17) ──────────────────────────────────

def _valid_qa_request() -> dict:
    """Minimal valid qa.request.v1 payload."""
    return {
        "request_id": "req-001",
        "sanitized_text": "gs maçı tahmin",
        "locale": "tr-TR",
        "sec_verdict": "pass",
        "emitted_at": "2026-05-26T10:00:00Z",
    }


class TestQaRequestV1LocaleEnum:
    """§10.17 first bullet: locale ∈ {tr-TR} at v1."""
    TOPIC = "qa.request.v1"

    def test_locale_tr_TR_accepted(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_qa_request())
        assert errors == [], f"Unexpected errors: {errors}"

    def test_locale_invalid_rejected(self):
        payload = {**_valid_qa_request(), "locale": "en-US"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("locale" in e.lower() or "enum" in e.lower() for e in errors), (
            f"Expected locale enum violation, got: {errors}"
        )

    def test_locale_empty_string_rejected(self):
        payload = {**_valid_qa_request(), "locale": ""}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("locale" in e.lower() or "enum" in e.lower() for e in errors)

    def test_locale_missing_rejected(self):
        payload = _valid_qa_request()
        del payload["locale"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("locale" in e.lower() for e in errors)


class TestQaRequestV1InputSourceEnum:
    """Optional request metadata hint for ASR / keyboard / paste input."""
    TOPIC = "qa.request.v1"

    def test_input_source_voice_accepted(self):
        payload = {**_valid_qa_request(), "input_source": "voice"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_input_source_unknown_accepted(self):
        payload = {**_valid_qa_request(), "input_source": "unknown"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_input_source_invalid_rejected(self):
        payload = {**_valid_qa_request(), "input_source": "speech"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("input_source" in e.lower() or "enum" in e.lower() for e in errors)


class TestQaRequestV1AnswerFormatEnum:
    """§10.23.7 request-side answer_format enum at v1."""
    TOPIC = "qa.request.v1"

    def test_answer_format_plain_accepted(self):
        payload = {**_valid_qa_request(), "answer_format": "plain"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_answer_format_screen_reader_accepted(self):
        payload = {**_valid_qa_request(), "answer_format": "screen_reader"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_answer_format_invalid_rejected(self):
        payload = {**_valid_qa_request(), "answer_format": "html"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("answer_format" in e.lower() or "enum" in e.lower() for e in errors)


# ── qa.intent.v1 locale enum (§10.17) ───────────────────────────────────

def _valid_qa_intent() -> dict:
    """Minimal valid qa.intent.v1 payload."""
    return {
        "schema_version": 4,
        "request_id": "req-001",
        "qa_correlation_id": "corr-001",
        "intent": "predict.match_outcome",
        "intent_confidence": 0.92,
        "entities": [],
        "intent_distribution": [
            {"intent": "predict.match_outcome", "probability": 0.92}
        ],
        "intent_model_version": "1.0.0",
        "intent_calibration_version": "1.0.0",
        "lexicon_versions": {},
        "normalized_text": "gs maçı tahmin",
        "confusables_resolved_count": 0,
        "locale": "tr-TR",
        "resolved_at_utc": "2026-05-26T10:00:00Z",
    }


class TestQaIntentV1LocaleEnum:
    """§10.17 first bullet: locale ∈ {tr-TR} at v1."""
    TOPIC = "qa.intent.v1"

    def test_locale_tr_TR_accepted(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_qa_intent())
        assert errors == [], f"Unexpected errors: {errors}"

    def test_locale_invalid_rejected(self):
        payload = {**_valid_qa_intent(), "locale": "de-DE"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("locale" in e.lower() or "enum" in e.lower() for e in errors), (
            f"Expected locale enum violation, got: {errors}"
        )


# ── qa.answer.v1 locale enum (§10.17) ───────────────────────────────────

def _valid_qa_answer() -> dict:
    """Minimal valid qa.answer.v1 payload."""
    return {
        "request_id": "req-001",
        "qa_correlation_id": "corr-001",
        "locale": "tr-TR",
        "intent": "predict.match_outcome",
        "answer_text": "Galatasaray maçını kazanma olasılığı %65.",
        "answer_format": "plain",
        "degraded": False,
        "humanizer_used": False,
        "proofreader_status": "pass",
        "emitted_at_utc": "2026-05-26T10:00:00Z",
        "nlp_pipeline_version": "10.0.0",
    }


class TestQaAnswerV1LocaleEnum:
    """§10.17 first bullet: locale ∈ {tr-TR} at v1."""
    TOPIC = "qa.answer.v1"

    def test_locale_tr_TR_accepted(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_qa_answer())
        assert errors == [], f"Unexpected errors: {errors}"

    def test_locale_invalid_rejected(self):
        payload = {**_valid_qa_answer(), "locale": "fr-FR"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("locale" in e.lower() or "enum" in e.lower() for e in errors), (
            f"Expected locale enum violation, got: {errors}"
        )


# ── Phase 10 §10.19 schema parity gate ───────────────────────────────────

class TestNlpSchemaParityGate:
    """§10.19 Cross-language schema parity.
    
    Extends the same schema validation gate that covers qa.request.v1 to all
    four Phase 10 NLP topics. These schemas enable:
      • qa.intent.v1: nlp.intent.v1 → nlp.dispatcher.v1 contract
      • qa.answer.v1: nlp.answer.v1 → Go gateway response serialization
      • nlp.event.v1: NLP control-plane observability (Phase 8 ops console)
      • nlp.alert.v1: NLP runtime alerts (Phase 8 maint reactors)
    
    Per the bullet: Go gateway needs only qa.answer.v1 for response
    serialization — pure data, no schema duplicate logic.
    """
    
    NLP_TOPICS = [
        "qa.intent.v1",
        "qa.answer.v1",
        "nlp.event.v1",
        "nlp.alert.v1",
    ]
    
    def test_all_four_nlp_schemas_exist(self):
        """Each of the four Phase 10 NLP topics has a schema file."""
        for topic in self.NLP_TOPICS:
            path = SCHEMA_DIR / f"{topic}.json"
            assert path.exists(), f"Schema file missing: {path}"
    
    def test_all_four_nlp_schemas_are_valid_json(self):
        """Each schema parses as valid JSON."""
        for topic in self.NLP_TOPICS:
            path = SCHEMA_DIR / f"{topic}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data, dict), f"{topic}: schema root must be object"
    
    def test_all_four_nlp_schemas_have_correct_id(self):
        """Each schema has $id matching negelir/swarm/<topic>."""
        for topic in self.NLP_TOPICS:
            schema = bus_schemas.load(topic)
            expected_id = f"negelir/swarm/{topic}"
            assert schema.get("$id") == expected_id, (
                f"{topic}: expected $id={expected_id!r}, got {schema.get('$id')!r}"
            )
    
    def test_all_four_nlp_schemas_have_json_schema_meta_field(self):
        """Each schema declares $schema (JSON Schema Draft version)."""
        for topic in self.NLP_TOPICS:
            schema = bus_schemas.load(topic)
            assert "$schema" in schema, f"{topic}: missing $schema meta-field"
    
    def test_all_four_nlp_schemas_have_type_field(self):
        """Each schema declares a 'type' field."""
        for topic in self.NLP_TOPICS:
            schema = bus_schemas.load(topic)
            assert "type" in schema, f"{topic}: missing 'type' field"
    
    def test_all_four_nlp_topics_in_known_topics(self):
        """All four NLP topics are returned by known_topics()."""
        known = bus_schemas.known_topics()
        for topic in self.NLP_TOPICS:
            assert topic in known, f"{topic} not in known_topics()"
    
    def test_qa_intent_v1_can_validate_minimal_payload(self):
        """qa.intent.v1 schema accepts a minimal valid payload."""
        errors = bus_schemas.validate("qa.intent.v1", _valid_qa_intent())
        assert errors == [], f"qa.intent.v1 validation failed: {errors}"

    def test_qa_intent_v1_accepts_quotative_frame_class(self):
        """qa.intent.v1 schema allows an optional quotative_frame_class property."""
        payload = _valid_qa_intent()
        payload["quotative_frame_class"] = "direct_quote_marker"
        errors = bus_schemas.validate("qa.intent.v1", payload)
        assert errors == [], f"qa.intent.v1 validation failed for quotative_frame_class: {errors}"

    def test_qa_answer_v1_can_validate_minimal_payload(self):
        """qa.answer.v1 schema accepts a minimal valid payload."""
        errors = bus_schemas.validate("qa.answer.v1", _valid_qa_answer())
        assert errors == [], f"qa.answer.v1 validation failed: {errors}"

    def test_qa_answer_v1_accepts_screen_reader_format(self):
        payload = {**_valid_qa_answer(), "answer_format": "screen_reader"}
        errors = bus_schemas.validate("qa.answer.v1", payload)
        assert errors == [], f"qa.answer.v1 validation failed for screen_reader: {errors}"

    def test_nlp_event_v1_can_validate_minimal_payload(self):
        """nlp.event.v1 schema accepts a minimal valid payload."""
        payload = {
            "kind": "lexicon_reloaded",
            "producer": "nlp.intent.v1",
            "emitted_at": "2026-05-26T10:00:00Z",
        }
        errors = bus_schemas.validate("nlp.event.v1", payload)
        assert errors == [], f"nlp.event.v1 validation failed: {errors}"
    
    def test_nlp_alert_v1_can_validate_minimal_payload(self):
        """nlp.alert.v1 schema accepts a minimal valid payload."""
        errors = bus_schemas.validate("nlp.alert.v1", _valid_nlp_alert())
        assert errors == [], f"nlp.alert.v1 validation failed: {errors}"

