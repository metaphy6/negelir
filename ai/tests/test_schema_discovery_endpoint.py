"""Tests for schema discovery endpoint (Phase 16.1, ledger #19).

Binding:
  - Emitter exposes GET /schemas on management port
  - Returns: active registry + SHA256 of each schema file + canonical-encoder version
  - FeedReader calls this on startup (in dev) and compares to in-tree copy
  - Mismatch → hard error
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add ai/ to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.common.feeds.management import (
    get_canonical_encoder_version,
    get_schema_files_sha256,
    get_schema_info,
    verify_remote_schemas,
)
from ai.common.feeds.reader import FeedReader


class TestSchemaDiscoveryEndpoint(unittest.TestCase):
    """Test suite for schema discovery functionality."""

    def test_get_canonical_encoder_version(self):
        """Canonical encoder version is 'v1' (Phase 16.1)."""
        version = get_canonical_encoder_version()
        assert version == "v1", f"Expected 'v1', got {version}"

    def test_get_schema_files_sha256_returns_dict(self):
        """get_schema_files_sha256 returns a dict of filename → SHA256."""
        shas = get_schema_files_sha256()
        assert isinstance(shas, dict), f"Expected dict, got {type(shas)}"
        assert len(shas) > 0, "Expected at least one schema file"
        
        # All values should be hex SHA256 (64 chars)
        for filename, sha in shas.items():
            assert len(sha) == 64, f"Invalid SHA256 for {filename}: {sha}"
            assert all(c in "0123456789abcdef" for c in sha), f"Invalid hex in SHA256 for {filename}"

    def test_get_schema_files_sha256_includes_registry(self):
        """get_schema_files_sha256 includes registry.json."""
        shas = get_schema_files_sha256()
        assert "registry.json" in shas, "registry.json should be included in schema files"

    def test_get_schema_info_structure(self):
        """get_schema_info returns expected structure."""
        info = get_schema_info()
        
        # Check top-level keys
        assert "registry" in info, "Missing 'registry' key"
        assert "schema_files_sha256" in info, "Missing 'schema_files_sha256' key"
        assert "canonical_encoder_version" in info, "Missing 'canonical_encoder_version' key"
        assert "generated_at" in info, "Missing 'generated_at' key"
        
        # Verify types
        assert isinstance(info["registry"], dict), "registry should be dict"
        assert isinstance(info["schema_files_sha256"], dict), "schema_files_sha256 should be dict"
        assert isinstance(info["canonical_encoder_version"], str), "canonical_encoder_version should be str"
        assert isinstance(info["generated_at"], str), "generated_at should be str"

    def test_get_schema_info_has_valid_registry(self):
        """get_schema_info's registry contains expected plane entries."""
        info = get_schema_info()
        registry = info["registry"]
        
        # Each plane should be present
        expected_planes = ["reference", "schedule", "score", "lineup", "editorial", "market"]
        for plane in expected_planes:
            assert plane in registry, f"Missing plane {plane} in registry"

    @patch("urllib.request.urlopen")
    def test_verify_remote_schemas_match_returns_match_true(self, mock_urlopen):
        """verify_remote_schemas returns schemas_match=True when schemas are identical."""
        # Get local info
        local_info = get_schema_info()
        
        # Mock remote response to return the same info
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(local_info).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response
        
        # Verify should succeed without raising
        result = verify_remote_schemas("http://localhost:9101")
        
        assert result["schemas_match"] is True, "Schemas should match"
        assert result["encoder_versions_match"] is True, "Encoder versions should match"

    @patch("urllib.request.urlopen")
    def test_verify_remote_schemas_mismatch_raises_error(self, mock_urlopen):
        """verify_remote_schemas raises ValueError when registry doesn't match."""
        local_info = get_schema_info()
        
        # Create remote info with different registry
        remote_info = local_info.copy()
        remote_info["registry"] = {"different": "registry"}
        
        # Mock remote response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(remote_info).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response
        
        # Should raise ValueError due to schema mismatch
        with pytest.raises(ValueError, match="Schema/encoder version mismatch"):
            verify_remote_schemas("http://localhost:9101")

    @patch("urllib.request.urlopen")
    def test_verify_remote_schemas_encoder_mismatch_raises_error(self, mock_urlopen):
        """verify_remote_schemas raises ValueError when encoder version doesn't match."""
        local_info = get_schema_info()
        
        # Create remote info with different encoder version
        remote_info = local_info.copy()
        remote_info["canonical_encoder_version"] = "v2"
        
        # Mock remote response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(remote_info).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_urlopen.return_value = mock_response
        
        # Should raise ValueError due to encoder version mismatch
        with pytest.raises(ValueError, match="Schema/encoder version mismatch"):
            verify_remote_schemas("http://localhost:9101")

    @patch.dict(os.environ, {"NEGELIR_SKIP_SCHEMA_VERIFICATION": "1"})
    def test_feedreader_skips_verification_when_env_set(self):
        """FeedReader skips schema verification when NEGELIR_SKIP_SCHEMA_VERIFICATION=1."""
        # This should not raise, even without a running emitter
        reader = FeedReader(verify_schema_on_init=True)
        assert reader.feeds_path == Path("/data/feeds")

    def test_feedreader_init_with_verification_disabled(self):
        """FeedReader can be initialized with schema verification disabled."""
        # This should not attempt any HTTP calls
        reader = FeedReader(verify_schema_on_init=False)
        assert reader.feeds_path == Path("/data/feeds")

    @patch("common.feeds.reader.logger")
    @patch("common.feeds.management.verify_remote_schemas")
    def test_feedreader_calls_verify_on_init(self, mock_verify, mock_logger):
        """FeedReader calls verify_remote_schemas on initialization."""
        # Mock the verify function to succeed
        mock_verify.return_value = {
            "schemas_match": True,
            "encoder_versions_match": True,
        }
        
        # Create reader with verification enabled
        reader = FeedReader(verify_schema_on_init=True)
        
        # verify_remote_schemas should have been called
        assert mock_verify.called, "verify_remote_schemas should be called on init"

    @patch("common.feeds.management.verify_remote_schemas")
    def test_feedreader_raises_on_schema_mismatch(self, mock_verify):
        """FeedReader raises when schema verification fails."""
        # Mock verify to raise a hard error
        mock_verify.side_effect = ValueError("Schema mismatch")
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="Schema mismatch"):
            FeedReader(verify_schema_on_init=True)


class TestSchemaDiscoveryHTTPResponse(unittest.TestCase):
    """Test schema discovery as HTTP response format."""

    def test_get_schema_info_is_json_serializable(self):
        """get_schema_info output is JSON-serializable."""
        info = get_schema_info()
        # Should not raise
        json_str = json.dumps(info)
        assert isinstance(json_str, str), "Should serialize to string"
        
        # Should be deserializable
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict), "Should deserialize to dict"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
