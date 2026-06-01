"""Phase 10 §10.0 — Wire authority schema tests.

Verifies the four new bus topics that Phase 10 introduces:
  qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1

Per AGENTS.md Rule 10: new schema files → happy + adversarial tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import swarm.sdk.schemas as bus_schemas
from swarm.sdk.wire_contracts import (
    NLP_ALERT_V1_ALLOWED_PRODUCERS,
    NLP_EVENT_V1_ALLOWED_PRODUCERS,
)

SCHEMA_DIR = Path(__file__).parent.parent / "swarm" / "sdk" / "schemas"

# ── Known kinds declared in §10.0 Wire authority bullet ────────────────
_NLP_EVENT_V1_KNOWN_KINDS = frozenset({
    "lexicon_reloaded",
    "lexicon_unreadable",
    "humanizer_disabled",
    "humanizer_breaker_open",
    "proofreader_blocked",
    "pii_in_answer_redacted",
    "intent_classifier_degraded",
    "dictionary_overflow",
    "slot_resolution_failed",
    "did_you_mean_offered",
    "cold_start_stage",
    "confusables_resolved",
    "singleflight_event_swept",
    "lexicon_old_generation_evicted",
})


# ── Helpers ─────────────────────────────────────────────────────────────

def _valid_qa_intent() -> dict:
    return {
        "request_id": "req-001",
        "qa_correlation_id": "corr-001",
        "intent": "predict.match_outcome",
        "intent_confidence": 0.91,
        "entities": [
            {
                "span_start": 0,
                "span_end": 11,
                "kind": "team",
                "canonical_id": "team:galatasaray",
                "confidence": 1.0,
                "source": "gazetteer",
                "lexicon_version": "1.0.0",
            }
        ],
        "intent_distribution": [
            {"intent": "predict.match_outcome", "probability": 0.91},
            {"intent": "predict.btts", "probability": 0.05},
        ],
        "intent_model_version": "1.0.0",
        "intent_calibration_version": "1.0.0",
        "lexicon_versions": {
            "teams": "1.0.0",
            "players": "1.0.0",
            "leagues": "1.0.0",
            "competitions": "1.0.0",
            "markets": "1.0.0",
            "dialects": "1.0.0",
        },
        "normalized_text": "galatasaray maçı",
        "confusables_resolved_count": 0,
        "locale": "tr-TR",
        "resolved_at_utc": "2026-05-27T10:00:00Z",
    }


def _valid_qa_answer() -> dict:
    return {
        "request_id": "req-001",
        "qa_correlation_id": "corr-abc",
        "answer_text": "Galatasaray maçı için tahmini göremiyorum.",
        "intent": "predict.match_outcome",
        "kind": "direct",
        "degraded": False,
        "degraded_reason": None,
        "tier_id_required": None,
        "citations": [],
        "emitted_at": "2026-05-27T10:00:01Z",
    }


def _valid_nlp_event(kind: str, extra: dict | None = None) -> dict:
    base = {
        "kind": kind,
        "producer": "nlp.intent.v1",
        "request_id": None,
        "emitted_at": "2026-05-27T10:00:00Z",
    }
    if extra:
        base.update(extra)
    return base


def _valid_nlp_alert() -> dict:
    return {
        "alert_id": "alert-001",
        "kind": "lexicon_unreadable",
        "severity": "error",
        "producer": "nlp.intent.v1",
        "reason": "SHA256 mismatch on teams.tr.yaml after partial write.",
        "request_id": None,
        "produced_at": "2026-05-27T10:00:00Z",
    }


# ── qa.intent.v1 ────────────────────────────────────────────────────────

class TestQaIntentV1Schema:
    TOPIC = "qa.intent.v1"

    def test_schema_file_exists_and_has_correct_id(self):
        p = SCHEMA_DIR / f"{self.TOPIC}.json"
        assert p.exists(), f"Schema file missing: {p}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["$id"] == f"negelir/swarm/{self.TOPIC}"

    def test_additional_properties_false(self):
        schema = bus_schemas.load(self.TOPIC)
        assert schema.get("additionalProperties") is False

    def test_happy_minimal(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_qa_intent())
        assert errors == [], errors

    def test_happy_no_entities(self):
        payload = {**_valid_qa_intent(), "entities": []}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], errors

    def test_missing_request_id(self):
        payload = _valid_qa_intent()
        del payload["request_id"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("request_id" in e for e in errors), errors

    def test_missing_intent(self):
        payload = _valid_qa_intent()
        del payload["intent"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("intent" in e for e in errors), errors

    def test_unknown_intent_value_rejected(self):
        payload = {**_valid_qa_intent(), "intent": "predict.nonexistent"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "unknown intent must be rejected"

    def test_entity_schema_requires_kind_field(self):
        # The lightweight validator does not recurse into array items, so we
        # assert the schema definition itself declares 'kind' as required
        # on the entity sub-object (contract enforcement at schema level).
        schema = bus_schemas.load(self.TOPIC)
        entity_schema = schema["properties"]["entities"]["items"]
        assert "kind" in entity_schema.get("required", []), (
            "entity items schema must require 'kind' field"
        )

    def test_adversarial_extra_field_rejected(self):
        payload = {**_valid_qa_intent(), "injected_field": "evil"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "extra field must be rejected (additionalProperties:false)"


# ── qa.answer.v1 ────────────────────────────────────────────────────────

class TestQaAnswerV1Schema:
    TOPIC = "qa.answer.v1"

    def test_schema_file_exists_and_has_correct_id(self):
        p = SCHEMA_DIR / f"{self.TOPIC}.json"
        assert p.exists(), f"Schema file missing: {p}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["$id"] == f"negelir/swarm/{self.TOPIC}"

    def test_additional_properties_false(self):
        schema = bus_schemas.load(self.TOPIC)
        assert schema.get("additionalProperties") is False

    def test_happy_minimal(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_qa_answer())
        assert errors == [], errors

    def test_happy_degraded_true(self):
        payload = {
            **_valid_qa_answer(),
            "degraded": True,
            "degraded_reason": "consensus_unavailable",
            "kind": "degraded",
        }
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors == [], errors

    def test_missing_request_id(self):
        payload = _valid_qa_answer()
        del payload["request_id"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("request_id" in e for e in errors), errors

    def test_missing_qa_correlation_id(self):
        payload = _valid_qa_answer()
        del payload["qa_correlation_id"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("qa_correlation_id" in e for e in errors), errors

    def test_unknown_kind_rejected(self):
        payload = {**_valid_qa_answer(), "kind": "totally_unknown"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "unknown kind must be rejected"

    def test_adversarial_extra_field_rejected(self):
        payload = {**_valid_qa_answer(), "hidden_field": "injection"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "extra field must be rejected"


# ── nlp.event.v1 ────────────────────────────────────────────────────────

class TestNlpEventV1Schema:
    TOPIC = "nlp.event.v1"

    def test_schema_file_exists_and_has_correct_id(self):
        p = SCHEMA_DIR / f"{self.TOPIC}.json"
        assert p.exists(), f"Schema file missing: {p}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["$id"] == f"negelir/swarm/{self.TOPIC}"

    def test_kind_discriminated_topic_registered(self):
        assert self.TOPIC in bus_schemas.kind_discriminated_topics()

    def test_all_declared_kinds_have_sub_schemas(self):
        actual = set(bus_schemas.known_kinds(self.TOPIC))
        missing = _NLP_EVENT_V1_KNOWN_KINDS - actual
        assert not missing, f"Missing per-kind sub-schemas: {missing}"

    def test_producer_set_matches_wire_contracts(self):
        schema = bus_schemas.load(self.TOPIC)
        schema_producers = set(schema["properties"]["producer"]["enum"])
        assert schema_producers == NLP_EVENT_V1_ALLOWED_PRODUCERS

    def test_happy_lexicon_reloaded(self):
        payload = _valid_nlp_event("lexicon_reloaded", {
            "lexicon_file": "teams.tr.yaml",
            "lexicon_version": "1.2.0",
            "entries_loaded": 512,
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_happy_intent_classifier_degraded(self):
        payload = _valid_nlp_event("intent_classifier_degraded", {
            "accuracy": 0.88,
            "floor": 0.92,
            "window_queries": 1000,
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_happy_did_you_mean_offered(self):
        payload = _valid_nlp_event("did_you_mean_offered", {
            "original_tokens": ["galatasray"],
            "suggestions": ["galatasaray"],
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_happy_cold_start_stage(self):
        payload = _valid_nlp_event("cold_start_stage", {
            "stage_index": 2,
            "stage_total": 6,
            "stage_name": "lexicon_ready",
            "elapsed_ms": 430,
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_happy_confusables_resolved(self):
        payload = _valid_nlp_event("confusables_resolved", {
            "resolved_count": 1,
            "sample_pairs": ["galatasray->galatasaray"],
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_happy_singleflight_event_swept(self):
        payload = _valid_nlp_event("singleflight_event_swept", {
            "swept_count": 17,
            "max_age_s": 60,
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_happy_lexicon_old_generation_evicted(self):
        payload = _valid_nlp_event("lexicon_old_generation_evicted", {
            "generation_id": "gen-20260531T095955Z",
            "remaining_generations": 2,
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors == [], errors

    def test_missing_producer_rejected(self):
        payload = {
            "kind": "lexicon_reloaded",
            "emitted_at": "2026-05-27T10:00:00Z",
            "lexicon_file": "teams.tr.yaml",
            "lexicon_version": "1.0.0",
            "entries_loaded": 1,
        }
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors, "missing producer must be rejected"

    def test_unknown_producer_rejected(self):
        payload = _valid_nlp_event("lexicon_reloaded", {
            "lexicon_file": "teams.tr.yaml",
            "lexicon_version": "1.0.0",
            "entries_loaded": 1,
        })
        payload["producer"] = "sec.input.v1"  # adversarial: wrong plane
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors, "sec.* producer must be rejected from nlp.event.v1"

    def test_unknown_kind_returns_error(self):
        payload = {"kind": "totally_unknown", "producer": "nlp.intent.v1",
                   "emitted_at": "2026-05-27T10:00:00Z"}
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors, "unknown kind must return an error"

    def test_confusables_resolved_missing_required_field_rejected(self):
        payload = _valid_nlp_event("confusables_resolved", {
            "sample_pairs": ["A->B"],
        })
        errors = bus_schemas.validate_kind(self.TOPIC, payload)
        assert errors, "missing resolved_count must be rejected"


# ── nlp.alert.v1 ────────────────────────────────────────────────────────

class TestNlpAlertV1Schema:
    TOPIC = "nlp.alert.v1"

    def test_schema_file_exists_and_has_correct_id(self):
        p = SCHEMA_DIR / f"{self.TOPIC}.json"
        assert p.exists(), f"Schema file missing: {p}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["$id"] == f"negelir/swarm/{self.TOPIC}"

    def test_additional_properties_false(self):
        schema = bus_schemas.load(self.TOPIC)
        assert schema.get("additionalProperties") is False

    def test_producer_set_matches_wire_contracts(self):
        schema = bus_schemas.load(self.TOPIC)
        schema_producers = set(schema["properties"]["producer"]["enum"])
        assert schema_producers == NLP_ALERT_V1_ALLOWED_PRODUCERS

    def test_happy_minimal(self):
        errors = bus_schemas.validate(self.TOPIC, _valid_nlp_alert())
        assert errors == [], errors

    def test_happy_all_severities(self):
        for sev in ("info", "warn", "error", "critical"):
            payload = {**_valid_nlp_alert(), "severity": sev}
            errors = bus_schemas.validate(self.TOPIC, payload)
            assert errors == [], f"severity={sev} failed: {errors}"

    def test_missing_alert_id(self):
        payload = _valid_nlp_alert()
        del payload["alert_id"]
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert any("alert_id" in e for e in errors), errors

    def test_invalid_severity(self):
        payload = {**_valid_nlp_alert(), "severity": "panic"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "invalid severity must be rejected"

    def test_reason_schema_declares_max_length(self):
        # The lightweight validator does not enforce maxLength at runtime;
        # assert the schema definition declares it so a future jsonschema
        # upgrade or producer-side guard picks it up.
        schema = bus_schemas.load(self.TOPIC)
        assert schema["properties"]["reason"].get("maxLength") == 1024, (
            "reason must declare maxLength=1024 in schema"
        )

    def test_adversarial_extra_field_rejected(self):
        payload = {**_valid_nlp_alert(), "secret_field": "leak"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "extra field must be rejected"

    def test_non_nlp_producer_rejected(self):
        payload = {**_valid_nlp_alert(), "producer": "maint.backup.v1"}
        errors = bus_schemas.validate(self.TOPIC, payload)
        assert errors, "maint.* producer must be rejected from nlp.alert.v1"

    def test_1021_13_known_alert_kinds_registered_in_schema_docs(self):
        """§10.21.13: new alert kinds must be registered as known kinds."""
        schema = bus_schemas.load(self.TOPIC)
        description = schema["properties"]["kind"]["description"]
        expected_kinds = {
            "nlp_intent_model_sha_mismatch",
            "nlp_lexicon_atomic_swap_failed",
            "nlp_singleflight_overflow",
            "nlp_template_render_used_raw_user_text",
            "nlp_spool_replay_text_unavailable",
            "nlp_citation_signature_verify_failed",
            "nlp_cold_start_timeout",
            "nlp_lexicon_feed_schema_too_new",
        }
        missing = sorted(kind for kind in expected_kinds if kind not in description)
        assert not missing, f"§10.21.13 known kinds missing from schema docs: {missing}"


# ── Phase 10 §10.19 — predict schema parity ────────────────────────────

class TestPredictSchemaQaCorrelationIdParity:
    """Phase 10 §10.19 boundary test: NLP-originated predict.request payloads
    must carry qa_correlation_id.

    Per ROADMAP §10.19 bullet:
      "Boundary test asserts every NLP-originated `predict.request.v1`
       carries it."
    """

    def test_predict_request_schema_declares_qa_correlation_id(self):
        """Verify predict.request.json schema declares qa_correlation_id."""
        schema = bus_schemas.load("predict.request")
        assert "qa_correlation_id" in schema["properties"], (
            "predict.request schema must declare qa_correlation_id field"
        )

    def test_predict_request_schema_declares_kind_schema_version(self):
        """Verify predict.request.json schema declares kind_schema_version."""
        schema = bus_schemas.load("predict.request")
        assert "kind_schema_version" in schema["properties"], (
            "predict.request schema must declare kind_schema_version field"
        )

    def test_predict_approved_v1_schema_declares_qa_correlation_id(self):
        """Verify predict.approved.v1 schema declares qa_correlation_id."""
        schema = bus_schemas.load("predict.approved.v1")
        assert "qa_correlation_id" in schema["properties"], (
            "predict.approved.v1 schema must declare qa_correlation_id field"
        )

    def test_predict_approved_v1_schema_declares_schema_version(self):
        """Verify predict.approved.v1 schema declares schema_version."""
        schema = bus_schemas.load("predict.approved.v1")
        assert "schema_version" in schema["properties"], (
            "predict.approved.v1 schema must declare schema_version field"
        )

    def test_predict_request_nlp_originated_carries_qa_correlation_id(self):
        """NLP-originated predict.request must carry qa_correlation_id."""
        # Happy path: NLP-originated request with qa_correlation_id
        payload = {
            "request_id": "req-001",
            "match_id": "match-123",
            "market": "1x2",
            "requested_at": "2026-05-27T10:00:00Z",
            "kind_schema_version": 2,
            "qa_correlation_id": "corr-abc",
        }
        errors = bus_schemas.validate("predict.request", payload)
        assert errors == [], f"NLP-originated predict.request failed: {errors}"

    def test_predict_request_legacy_without_qa_correlation_id(self):
        """Legacy predict.request (schema_version 1) may omit qa_correlation_id."""
        payload = {
            "request_id": "req-001",
            "match_id": "match-123",
            "market": "1x2",
            "requested_at": "2026-05-27T10:00:00Z",
            "kind_schema_version": 1,
            # qa_correlation_id intentionally omitted
        }
        errors = bus_schemas.validate("predict.request", payload)
        assert errors == [], f"Legacy predict.request failed: {errors}"

    def test_predict_approved_v1_with_qa_correlation_id(self):
        """predict.approved.v1 with schema_version=2 and qa_correlation_id."""
        payload = {
            "request_id": "req-001",
            "prediction_id": "pred-123",
            "match_id": "match-123",
            "market": "1x2",
            "approved_at": "2026-05-27T10:00:01Z",
            "approved_by": ["proof.sanity.v1"],
            "verdict_count": 1,
            "quorum": 1,
            "final": {"prediction_id": "pred-123"},
            "calibration_version": 0,
            "schema_version": 2,
            "qa_correlation_id": "corr-abc",
        }
        errors = bus_schemas.validate("predict.approved.v1", payload)
        assert errors == [], f"predict.approved.v1 with qa_correlation_id failed: {errors}"

    def test_predict_approved_v1_legacy_without_qa_correlation_id(self):
        """predict.approved.v1 legacy (schema_version=1) omits qa_correlation_id."""
        payload = {
            "request_id": "req-001",
            "prediction_id": "pred-123",
            "match_id": "match-123",
            "market": "1x2",
            "approved_at": "2026-05-27T10:00:01Z",
            "approved_by": ["proof.sanity.v1"],
            "verdict_count": 1,
            "quorum": 1,
            "final": {"prediction_id": "pred-123"},
            "calibration_version": 0,
            "schema_version": 1,
            # qa_correlation_id intentionally omitted
        }
        errors = bus_schemas.validate("predict.approved.v1", payload)
        assert errors == [], f"Legacy predict.approved.v1 failed: {errors}"

    def test_predict_approved_v1_dataclass_roundtrip_with_qa_correlation_id(self):
        """PredictApproved dataclass roundtrip with qa_correlation_id."""
        from swarm.agents.payloads import PredictApproved

        data = {
            "request_id": "req-001",
            "prediction_id": "pred-123",
            "match_id": "match-123",
            "market": "1x2",
            "approved_at": "2026-05-27T10:00:01Z",
            "approved_by": ["proof.sanity.v1"],
            "verdict_count": 1,
            "quorum": 1,
            "final": {"prediction_id": "pred-123"},
            "calibration_version": 0,
            "schema_version": 2,
            "qa_correlation_id": "corr-abc",
        }
        obj = PredictApproved.from_dict(data)
        assert obj.qa_correlation_id == "corr-abc"
        assert obj.schema_version == 2

        # Roundtrip via as_dict
        roundtrip = obj.as_dict()
        assert roundtrip["qa_correlation_id"] == "corr-abc"
        assert roundtrip["schema_version"] == 2

    def test_predict_approved_v1_dataclass_defaults_schema_version_1(self):
        """PredictApproved dataclass defaults to schema_version=1 for backward compat."""
        from swarm.agents.payloads import PredictApproved

        # Legacy payload without schema_version / qa_correlation_id
        data = {
            "request_id": "req-001",
            "prediction_id": "pred-123",
            "match_id": "match-123",
            "market": "1x2",
            "approved_at": "2026-05-27T10:00:01Z",
            "approved_by": ["proof.sanity.v1"],
            "verdict_count": 1,
            "quorum": 1,
            "final": {"prediction_id": "pred-123"},
            "calibration_version": 0,
        }
        obj = PredictApproved.from_dict(data)
        assert obj.schema_version == 1, "Legacy payload must default to schema_version=1"
        assert obj.qa_correlation_id is None, "Legacy payload has no qa_correlation_id"
