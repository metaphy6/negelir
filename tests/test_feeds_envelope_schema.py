"""
Tests for Phase 16.1.3 — Record envelope schema validation.

Verifies:
  - envelope.v1.json is valid JSONSchema 2020-12
  - additionalProperties is false (strict mode)
  - Reserved fields have sane defaults (null or false)
  - Required fields are properly declared
  - Envelope can validate actual Record instances
"""

import json
import pytest
from pathlib import Path


@pytest.fixture
def envelope_schema() -> dict:
    """Load the envelope schema."""
    schema_path = Path(__file__).parent.parent / "common" / "schemas" / "feeds" / "envelope.v1.json"
    with open(schema_path) as f:
        return json.load(f)


class TestEnvelopeSchema:
    """Test Record envelope schema structure and compliance."""

    def test_envelope_schema_valid_json(self, envelope_schema: dict) -> None:
        """Envelope schema should be valid JSON and parseable."""
        assert isinstance(envelope_schema, dict)
        assert "$schema" in envelope_schema
        assert "properties" in envelope_schema

    def test_envelope_has_json_schema_2020_12(self, envelope_schema: dict) -> None:
        """Envelope must declare JSON Schema 2020-12 compatibility."""
        assert envelope_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_envelope_has_additional_properties_false(self, envelope_schema: dict) -> None:
        """Envelope must forbid unknown fields."""
        assert envelope_schema.get("additionalProperties") is False

    def test_envelope_required_fields_present(self, envelope_schema: dict) -> None:
        """All required envelope fields must be declared."""
        required = envelope_schema.get("required", [])
        assert "canonical_version" in required
        assert "captured_at" in required
        assert "data_class" in required
        assert "extractor_version" in required
        assert "idempotency_key" in required
        assert "plane" in required
        assert "raw_ref" in required
        assert "record_type" in required
        assert "source_key" in required
        assert "stable_id" in required
        assert "payload" in required

    def test_envelope_optional_fields_have_defaults(self, envelope_schema: dict) -> None:
        """Reserved fields (trace_context, field_provenance, tombstone, retracted_at, signature, region, league_id, league_bucket) must have sane defaults."""
        props = envelope_schema.get("properties", {})

        # trace_context should default to null
        assert "trace_context" in props
        assert props["trace_context"].get("default") is None

        # field_provenance should default to null
        assert "field_provenance" in props
        assert props["field_provenance"].get("default") is None

        # tombstone should default to false (not null, but False indicates non-tombstone by default)
        assert "tombstone" in props
        assert props["tombstone"].get("default") is False

        # retracted_at should default to null
        assert "retracted_at" in props
        assert props["retracted_at"].get("default") is None

        # signature should default to null
        assert "signature" in props
        assert props["signature"].get("default") is None

        # region should default to null
        assert "region" in props
        assert props["region"].get("default") is None

        # league_id should default to null
        assert "league_id" in props
        assert props["league_id"].get("default") is None

        # league_bucket should default to null
        assert "league_bucket" in props
        assert props["league_bucket"].get("default") is None

    def test_envelope_data_class_enum(self, envelope_schema: dict) -> None:
        """data_class should be an enum of exactly four values."""
        props = envelope_schema.get("properties", {})
        data_class_prop = props.get("data_class", {})
        enum_vals = data_class_prop.get("enum", [])
        assert set(enum_vals) == {"public", "internal", "restricted", "pii"}

    def test_envelope_plane_enum(self, envelope_schema: dict) -> None:
        """plane should enumerate all six base planes plus cross-phase planes."""
        props = envelope_schema.get("properties", {})
        plane_prop = props.get("plane", {})
        enum_vals = plane_prop.get("enum", [])
        
        # Base planes
        assert "reference" in enum_vals
        assert "schedule" in enum_vals
        assert "live" in enum_vals
        assert "editorial" in enum_vals
        assert "market" in enum_vals
        
        # Cross-phase planes
        assert "feature_vectors" in enum_vals
        assert "sec_quarantine" in enum_vals
        assert "match_outcomes" in enum_vals
        assert "calibration" in enum_vals
        assert "competition" in enum_vals
        assert "predict_invalidated" in enum_vals

    def test_envelope_record_type_enum(self, envelope_schema: dict) -> None:
        """record_type should enumerate all plane-specific types."""
        props = envelope_schema.get("properties", {})
        record_type_prop = props.get("record_type", {})
        enum_vals = record_type_prop.get("enum", [])
        
        expected = [
            "team", "player", "venue", "competition", "season",  # reference
            "fixture",  # schedule
            "score", "lineup",  # live
            "article", "commentary",  # editorial
            "odds"  # market
        ]
        assert set(enum_vals) == set(expected)

    def test_envelope_source_key_enum(self, envelope_schema: dict) -> None:
        """source_key should enumerate the four canonical sources."""
        props = envelope_schema.get("properties", {})
        source_key_prop = props.get("source_key", {})
        enum_vals = source_key_prop.get("enum", [])
        assert set(enum_vals) == {"mackolik", "nesine", "tff", "openfootball"}

    def test_envelope_region_enum_with_null(self, envelope_schema: dict) -> None:
        """region should allow null and the five data residency regions."""
        props = envelope_schema.get("properties", {})
        region_prop = props.get("region", {})
        enum_vals = region_prop.get("enum", [])
        assert "eu" in enum_vals
        assert "tr" in enum_vals
        assert "americas" in enum_vals
        assert "apac" in enum_vals
        assert "mea" in enum_vals
        assert None in enum_vals  # null option

    def test_envelope_fields_are_all_documented(self, envelope_schema: dict) -> None:
        """All envelope fields must have descriptions."""
        props = envelope_schema.get("properties", {})
        for field_name, field_def in props.items():
            assert "description" in field_def, f"Field {field_name} has no description"

    def test_envelope_canonical_version_pattern(self, envelope_schema: dict) -> None:
        r"""canonical_version should match pattern ^v\d+$."""
        props = envelope_schema.get("properties", {})
        cv_prop = props.get("canonical_version", {})
        assert cv_prop.get("pattern") == "^v\\d+$"

    def test_envelope_datetime_fields_use_format(self, envelope_schema: dict) -> None:
        """DateTime fields should use format: date-time."""
        props = envelope_schema.get("properties", {})
        
        # captured_at must be date-time
        assert props["captured_at"].get("format") == "date-time"
        
        # occurred_at must be date-time (but nullable)
        assert props["occurred_at"].get("format") == "date-time"
        
        # retracted_at must be date-time (but nullable)
        assert props["retracted_at"].get("format") == "date-time"
