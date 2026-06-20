"""Tests for envelope payload size cap (Phase 16.1).

Covers:
  - Config key NEGELIR_EMITTER_MAX_PAYLOAD_BYTES loads correctly
  - Envelope schema accepts truncated_at_bytes field (nullable integer)
  - Default value is 64 KiB (65536 bytes)
"""

import json
from pathlib import Path

import pytest

from ai.common.config import Config


class TestEnvelopePayloadSizeCap:
    """Payload size cap configuration and schema."""

    def test_emitter_max_payload_bytes_config_loads_default(self):
        """Default NEGELIR_EMITTER_MAX_PAYLOAD_BYTES is 64 KiB."""
        cfg = Config()
        assert cfg.emitter_max_payload_bytes == 64 * 1024

    def test_emitter_max_payload_bytes_config_from_env(self, monkeypatch):
        """Config respects NEGELIR_EMITTER_MAX_PAYLOAD_BYTES env var."""
        monkeypatch.setenv("NEGELIR_EMITTER_MAX_PAYLOAD_BYTES", "32768")
        cfg = Config()
        assert cfg.emitter_max_payload_bytes == 32768

    def test_envelope_schema_accepts_truncated_at_bytes_null(self):
        """Envelope schema accepts truncated_at_bytes: null."""
        envelope_schema_path = (
            Path(__file__).resolve().parent.parent
            / "common" / "schemas" / "feeds" / "envelope.v1.json"
        )
        assert envelope_schema_path.exists(), f"Schema not found at {envelope_schema_path}"

        with open(envelope_schema_path, "r") as f:
            schema = json.load(f)

        assert "truncated_at_bytes" in schema["properties"]
        field_spec = schema["properties"]["truncated_at_bytes"]
        assert field_spec["type"] == ["integer", "null"]
        assert field_spec["default"] is None

    def test_envelope_schema_rejects_unknown_fields(self):
        """Envelope schema has additionalProperties: false."""
        envelope_schema_path = (
            Path(__file__).resolve().parent.parent
            / "common" / "schemas" / "feeds" / "envelope.v1.json"
        )
        with open(envelope_schema_path, "r") as f:
            schema = json.load(f)

        assert schema.get("additionalProperties") is False
