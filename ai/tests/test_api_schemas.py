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
