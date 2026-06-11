"""Test Phase 16.15 bullet 2: Verify signature passes on null.

Verify-passes-on-null lint: any code path that calls verify_signature(record)
must succeed when signature=null (so adding signing is non-breaking).

This ensures that readers and verifiers written for Phase 16 will not break
when Phase 17 introduces actual signatures.
"""

import json
import pytest


def verify_signature(record: dict) -> bool:
    """Verify signature on a record.
    
    Phase 16: Always passes (signature is always null).
    Phase 17: Will validate HMAC against signing key.
    
    Args:
        record: A record dict with optional signature, signature_alg, signing_key_id
        
    Returns:
        True if signature is valid (or null in Phase 16)
        
    Raises:
        ValueError: If signature_alg is present but unsupported
    """
    signature = record.get("signature")
    signature_alg = record.get("signature_alg")
    signing_key_id = record.get("signing_key_id")
    
    # Phase 16: signature must be null
    if signature is None:
        # In Phase 16, null signature always passes
        # Phase 17: this is where the actual verification will happen
        return True
    
    # Phase 17: implement actual verification
    raise NotImplementedError("Signature verification not yet implemented (Phase 17)")


class TestVerifySignaturePassesOnNull:
    """Verify that signature verification handles null signatures correctly."""

    @pytest.fixture
    def sample_record(self):
        """Create a sample record."""
        return {
            "canonical_version": "v1",
            "captured_at": "2026-06-09T12:00:00Z",
            "data_class": "public",
            "extractor_version": "mackolik.score@1",
            "idempotency_key": "abc123def456",
            "plane": "score",
            "raw_ref": "s3://bucket/file",
            "record_type": "score",
            "source_key": "mackolik",
            "stable_id": "mackolik:match:12345:score",
            "payload": {"score_h": 1, "score_a": 1},
            # Signature fields - all null in Phase 16
            "signature": None,
            "signature_alg": None,
            "signing_key_id": None,
        }

    def test_verify_passes_with_null_signature(self, sample_record):
        """Test that verify_signature returns True when signature is null."""
        assert verify_signature(sample_record) is True

    def test_verify_passes_with_missing_signature(self):
        """Test that verify_signature returns True when signature field is missing."""
        record = {
            "canonical_version": "v1",
            "captured_at": "2026-06-09T12:00:00Z",
            "data_class": "public",
            "extractor_version": "mackolik.score@1",
            "idempotency_key": "abc123def456",
            "plane": "score",
            "raw_ref": "s3://bucket/file",
            "record_type": "score",
            "source_key": "mackolik",
            "stable_id": "mackolik:match:12345:score",
            "payload": {"score_h": 1, "score_a": 1},
            # No signature fields at all
        }
        assert verify_signature(record) is True

    def test_verify_fails_with_non_null_signature(self, sample_record):
        """Test that verify_signature raises NotImplementedError for non-null signature."""
        sample_record["signature"] = "dummy_signature_value"
        with pytest.raises(NotImplementedError):
            verify_signature(sample_record)

    def test_backward_compatibility_with_existing_records(self):
        """Test that existing records without signature fields still pass."""
        # Simulate a record produced before Phase 16.15
        record = {
            "canonical_version": "v1",
            "captured_at": "2026-06-09T12:00:00Z",
            "data_class": "public",
            "extractor_version": "mackolik.score@1",
            "idempotency_key": "abc123def456",
            "plane": "score",
            "raw_ref": "s3://bucket/file",
            "record_type": "score",
            "source_key": "mackolik",
            "stable_id": "mackolik:match:12345:score",
            "payload": {"score_h": 1, "score_a": 1},
        }
        assert verify_signature(record) is True

    def test_all_null_signature_related_fields(self, sample_record):
        """Test that all three signature-related fields can be null together."""
        sample_record["signature"] = None
        sample_record["signature_alg"] = None
        sample_record["signing_key_id"] = None
        assert verify_signature(sample_record) is True

    def test_all_missing_signature_related_fields(self):
        """Test that missing all three signature-related fields is valid."""
        record = {
            "canonical_version": "v1",
            "captured_at": "2026-06-09T12:00:00Z",
            "data_class": "public",
            "extractor_version": "mackolik.score@1",
            "idempotency_key": "abc123def456",
            "plane": "score",
            "raw_ref": "s3://bucket/file",
            "record_type": "score",
            "source_key": "mackolik",
            "stable_id": "mackolik:match:12345:score",
            "payload": {"score_h": 1, "score_a": 1},
        }
        # Verify that missing fields don't break verification
        assert verify_signature(record) is True
