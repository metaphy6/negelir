"""
Test: test_envelope_reserved_fields_default_safe.py
Phase 16.1 contract validation — reserved fields have safe defaults.

Validates:
1. All reserved envelope fields (signature, field_provenance, tombstone, retracted_at,
   region, league_id, league_bucket, trace_context) have safe default values
2. Reserved fields are nullable (type includes null) or have default: false/null
3. Adding a reserved field later is not a schema bump (already present with safe default)

Fulfills Phase 16.1 requirement: "Reserved fields (...) ship with sane defaults so
adding them later is not a schema bump (ledger #20, #31, #33)."

Fulfills ledger #20 requirement: "The envelope field must be reserved now
(signature: str|null) so adding HMAC at Phase 17 isn't a schema bump."
"""

import json
import os
import pytest


@pytest.fixture
def envelope_schema():
    """Load the envelope schema."""
    schema_path = os.path.join(
        os.path.dirname(__file__),
        "../common/schemas/feeds/envelope.v1.json"
    )
    with open(schema_path) as f:
        return json.load(f)


class TestReservedFieldsDefaults:
    """Validate that reserved fields have safe defaults."""

    # Reserved fields that must be present in the envelope schema
    RESERVED_FIELDS = {
        "signature",           # Phase 17: for per-record HMAC
        "signature_alg",       # Phase 17: algorithm for signature
        "signing_key_id",      # Phase 17: key version
        "field_provenance",    # Phase 13.36: source attribution
        "tombstone",           # Phase 16: retraction support
        "retracted_at",        # Phase 16: when retracted
        "region",              # Phase 13.24: data residency
        "league_id",           # Phase 13.2: league context
        "league_bucket",       # Phase 13: tenant isolation
        "trace_context",       # Phase 16.31: OTEL tracing
    }

    def test_all_reserved_fields_present(self, envelope_schema):
        """All reserved fields must be in the envelope schema."""
        properties = envelope_schema.get("properties", {})
        for field in self.RESERVED_FIELDS:
            assert field in properties, \
                f"Reserved field '{field}' not found in envelope schema"

    def test_reserved_fields_are_optional(self, envelope_schema):
        """Reserved fields must be optional (not in 'required' array)."""
        required = set(envelope_schema.get("required", []))
        for field in self.RESERVED_FIELDS:
            assert field not in required, \
                f"Reserved field '{field}' must be optional (not in required array)"

    def test_reserved_fields_have_safe_defaults(self, envelope_schema):
        """Reserved fields must have safe default values."""
        properties = envelope_schema.get("properties", {})

        for field in self.RESERVED_FIELDS:
            field_schema = properties.get(field, {})

            # Must be nullable or have a default
            field_type = field_schema.get("type")
            has_default = "default" in field_schema
            is_nullable = (
                field_type == ["object", "null"] or
                field_type == ["string", "null"] or
                field_type == ["boolean", "null"] or
                (isinstance(field_type, list) and "null" in field_type)
            )

            assert has_default or is_nullable, \
                f"Reserved field '{field}' must have a default or be nullable. " \
                f"Got type={field_type}, default={field_schema.get('default')}"

            # If it has a default, it must be safe (false, null, or empty string)
            if has_default:
                default_val = field_schema.get("default")
                assert default_val in (False, None, ""), \
                    f"Reserved field '{field}' has unsafe default: {default_val}. " \
                    f"Safe defaults are: False, None, or empty string."

    def test_signature_field_reserved_for_phase_17(self, envelope_schema):
        """Signature field must exist but be null (Phase 17 wire-up)."""
        properties = envelope_schema.get("properties", {})
        sig_field = properties.get("signature", {})

        # Must be string|null
        field_type = sig_field.get("type")
        assert field_type == ["string", "null"] or field_type == ["null", "string"], \
            f"Signature field must be string|null, got {field_type}"

        # Must have default null
        assert sig_field.get("default") is None, \
            f"Signature field must default to null, got {sig_field.get('default')}"

    def test_field_provenance_nullable(self, envelope_schema):
        """field_provenance must be object|null per Phase 13.36."""
        properties = envelope_schema.get("properties", {})
        provenance_field = properties.get("field_provenance", {})

        field_type = provenance_field.get("type")
        assert field_type == ["object", "null"] or field_type == ["null", "object"], \
            f"field_provenance must be object|null, got {field_type}"

        # Must default to null
        assert provenance_field.get("default") is None, \
            f"field_provenance must default to null, got {provenance_field.get('default')}"

    def test_tombstone_field_boolean_with_false_default(self, envelope_schema):
        """tombstone field must be boolean with false default (not retracted)."""
        properties = envelope_schema.get("properties", {})
        tombstone_field = properties.get("tombstone", {})

        field_type = tombstone_field.get("type")
        # Should allow bool or [bool, null]
        if isinstance(field_type, str):
            assert field_type == "boolean", \
                f"tombstone type must be boolean, got {field_type}"
        else:
            assert "boolean" in field_type, \
                f"tombstone type must include boolean, got {field_type}"

        # Must default to false (not tombstoned)
        assert tombstone_field.get("default") is False, \
            f"tombstone must default to False, got {tombstone_field.get('default')}"

    def test_retracted_at_nullable_timestamp(self, envelope_schema):
        """retracted_at must be datetime|null per Phase 16.13."""
        properties = envelope_schema.get("properties", {})
        retracted_at_field = properties.get("retracted_at", {})

        field_type = retracted_at_field.get("type")
        assert field_type == ["string", "null"] or field_type == ["null", "string"], \
            f"retracted_at must be string|null, got {field_type}"

        # Must have format date-time
        assert retracted_at_field.get("format") == "date-time", \
            f"retracted_at must have format: date-time"

        # Must default to null (not retracted)
        assert retracted_at_field.get("default") is None, \
            f"retracted_at must default to null, got {retracted_at_field.get('default')}"

    def test_region_enum_includes_null(self, envelope_schema):
        """region must be one of: eu, tr, americas, apac, mea, null."""
        properties = envelope_schema.get("properties", {})
        region_field = properties.get("region", {})

        field_type = region_field.get("type")
        assert field_type == ["string", "null"] or field_type == ["null", "string"], \
            f"region must be string|null, got {field_type}"

        # Must have enum with null
        enum_vals = region_field.get("enum", [])
        assert None in enum_vals, f"region enum must include null, got {enum_vals}"

        # Must default to null (no region specified)
        assert region_field.get("default") is None, \
            f"region must default to null, got {region_field.get('default')}"

    def test_trace_context_nullable(self, envelope_schema):
        """trace_context must be nullable object per Phase 16.31."""
        properties = envelope_schema.get("properties", {})
        trace_field = properties.get("trace_context", {})

        field_type = trace_field.get("type")
        assert field_type == ["object", "null"] or field_type == ["null", "object"], \
            f"trace_context must be object|null, got {field_type}"

        # Must default to null
        assert trace_field.get("default") is None, \
            f"trace_context must default to null, got {trace_field.get('default')}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
