"""Test Phase 16.15 bullet 1: Reserved envelope fields for signing.

Phase 17 will add HMAC-per-Record signing support. This phase reserves
the surface so adding signing later is not a schema bump.

Ledger #20: Per-record signing is Phase 17's problem, but the envelope
**field** must be reserved now so adding HMAC at Phase 17 isn't a schema
bump. Phase 16 ships the fields always-`null`.
"""

import json
import pytest


class TestSignatureFieldReserved:
    """Verify signature and related fields are reserved in envelope schema."""

    @pytest.fixture
    def envelope_schema(self):
        """Load the envelope schema."""
        with open("ai/common/schemas/feeds/envelope.v1.json") as f:
            return json.load(f)

    def test_signature_field_present(self, envelope_schema):
        """Test that signature field is present in envelope schema."""
        assert "signature" in envelope_schema["properties"]

    def test_signature_alg_field_present(self, envelope_schema):
        """Test that signature_alg field is present in envelope schema."""
        assert "signature_alg" in envelope_schema["properties"]

    def test_signing_key_id_field_present(self, envelope_schema):
        """Test that signing_key_id field is present in envelope schema."""
        assert "signing_key_id" in envelope_schema["properties"]

    def test_signature_defaults_to_null(self, envelope_schema):
        """Test that signature field defaults to null."""
        sig_schema = envelope_schema["properties"]["signature"]
        assert sig_schema["default"] is None
        assert sig_schema["type"] == ["string", "null"]

    def test_signature_alg_defaults_to_null(self, envelope_schema):
        """Test that signature_alg field defaults to null."""
        alg_schema = envelope_schema["properties"]["signature_alg"]
        assert alg_schema["default"] is None
        assert alg_schema["type"] == ["string", "null"]
        # Verify the only non-null enum value is hmac-sha256-v1
        non_null_enums = [e for e in alg_schema["enum"] if e is not None]
        assert "hmac-sha256-v1" in non_null_enums

    def test_signing_key_id_defaults_to_null(self, envelope_schema):
        """Test that signing_key_id field defaults to null."""
        key_id_schema = envelope_schema["properties"]["signing_key_id"]
        assert key_id_schema["default"] is None
        assert key_id_schema["type"] == ["string", "null"]

    def test_signature_fields_not_required(self, envelope_schema):
        """Test that signature fields are not in the required list."""
        required = envelope_schema["required"]
        assert "signature" not in required
        assert "signature_alg" not in required
        assert "signing_key_id" not in required

    def test_fields_support_null_values(self, envelope_schema):
        """Test that all three signing fields support null values."""
        for field_name in ["signature", "signature_alg", "signing_key_id"]:
            schema = envelope_schema["properties"][field_name]
            # Should allow null type
            assert isinstance(schema["type"], list)
            assert "null" in schema["type"]

    def test_envelope_description_lists_new_fields(self, envelope_schema):
        """Test that the envelope description mentions the new fields."""
        description = envelope_schema["description"]
        # Verify the fields are mentioned in the list of keys
        assert "signature" in description
        assert "signature_alg" in description
        assert "signing_key_id" in description
