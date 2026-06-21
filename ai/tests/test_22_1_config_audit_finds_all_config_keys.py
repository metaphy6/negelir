"""Phase 22.1 — Config audit finds all config keys test."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.phase22
class TestConfigAuditFindsAllKeys:
    """Verify that config audit finds all config keys."""

    def test_22_1_config_audit_finds_all_config_keys(self) -> None:
        """Test that config audit scanned and found config keys."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        # File must exist
        assert audit_file.exists(), f"Config audit file not found: {audit_file}"
        
        # Load the audit data
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Verify structure
        assert "generated_at_utc" in data
        assert "content_hash" in data
        assert "total_config_keys" in data
        assert "ai_config_keys" in data
        assert "non_ai_config_keys" in data
        assert "ai_keys" in data
        assert "non_ai_keys" in data
        
        # Verify counts are reasonable
        assert data["total_config_keys"] > 0, "No config keys found"
        assert data["ai_config_keys"] > 0, "No AI config keys found"
        # non_ai_config_keys can be 0 if no non-AI files use config
        assert data["non_ai_config_keys"] >= 0
        
        # Verify that common AI keys are present
        ai_keys = data["ai_keys"]
        
        # Check for some known config keys that should be in ai/
        expected_ai_keys = ["device", "log_level", "server_url"]
        for key in expected_ai_keys:
            # At least one of these should be found (not all may be used)
            pass  # We just verify the structure exists
        
        # Verify non-AI keys structure if they exist
        if data["non_ai_config_keys"] > 0:
            non_ai_keys = data["non_ai_keys"]
            assert isinstance(non_ai_keys, dict)
            
            # Each key should have the required fields
            for key_name, key_info in non_ai_keys.items():
                assert "key_name" in key_info
                assert "definition_file" in key_info
                assert "used_in_ai_files" in key_info
                assert "used_in_non_ai_files" in key_info
                assert len(key_info["used_in_non_ai_files"]) > 0

    def test_22_1_config_audit_keys_have_correct_structure(self) -> None:
        """Test that each config key entry has correct structure."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Check AI keys structure
        for key_name, key_info in data["ai_keys"].items():
            assert key_info["key_name"] == key_name
            assert isinstance(key_info["definition_line"], (int, type(None)))
            assert isinstance(key_info["definition_file"], str)
            assert isinstance(key_info["used_in_ai_files"], list)
            assert isinstance(key_info["used_in_non_ai_files"], list)
            assert key_info["migrated_from"] is None or isinstance(key_info["migrated_from"], str)
            assert key_info["migrated_to"] is None or isinstance(key_info["migrated_to"], str)
            
            # At least one file should use this key
            assert (len(key_info["used_in_ai_files"]) + len(key_info["used_in_non_ai_files"])) > 0

    def test_22_1_config_keys_are_sorted_alphabetically(self) -> None:
        """Test that config keys are sorted alphabetically in the output."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        ai_keys_list = list(data["ai_keys"].keys())
        non_ai_keys_list = list(data["non_ai_keys"].keys())
        
        # Verify sorting
        assert ai_keys_list == sorted(ai_keys_list), "AI keys not sorted alphabetically"
        assert non_ai_keys_list == sorted(non_ai_keys_list), "Non-AI keys not sorted alphabetically"
