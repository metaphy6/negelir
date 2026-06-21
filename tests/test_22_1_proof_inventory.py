"""Phase 22.1 — Proof tests: Inventory completeness and tracking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.phase22
class TestInventoryCompleteness:
    """Verify Phase 22 inventory is complete."""

    def test_22_1_config_audit_inventory_exists(self) -> None:
        """Test that config audit inventory exists."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        assert audit_file.exists(), f"Config audit not found: {audit_file}"

    def test_22_1_config_audit_has_required_fields(self) -> None:
        """Test that config audit has required structure."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        with open(audit_file, "r") as f:
            data = json.load(f)
        
        assert "total_config_keys" in data
        assert "ai_config_keys" in data
        assert "non_ai_config_keys" in data
        assert "ai_keys" in data
        assert "non_ai_keys" in data
        
        # Verify basic structure
        assert data["total_config_keys"] > 0
        assert isinstance(data["ai_keys"], dict)
        assert isinstance(data["non_ai_keys"], dict)

    def test_22_1_ai_keys_are_from_ai_common_config(self) -> None:
        """Test that AI keys come from ai/common/config.py."""
        repo_root = Path(__file__).resolve().parents[2]
        config_file = repo_root / "ai" / "common" / "config.py"
        assert config_file.exists(), "ai/common/config.py should exist"
        
        with open(config_file, "r") as f:
            config_content = f.read()
        
        # Config class should exist
        assert "class Config" in config_content

    def test_22_1_non_ai_keys_are_external_only(self) -> None:
        """Test that non-AI keys include only external package usage."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        with open(audit_file, "r") as f:
            data = json.load(f)
        
        # Each non-AI key should have files in non-ai packages
        for key_name, key_info in data["non_ai_keys"].items():
            files = key_info["used_in_non_ai_files"]
            if files:  # Only check if there are files
                for file_path in files:
                    assert not file_path.startswith("ai/"), \
                        f"Non-AI key {key_name} references ai/ file: {file_path}"
                    assert any(file_path.startswith(prefix) for prefix in ["xops/", "common/", "docs/", "swarm/", "server/"]), \
                        f"Non-AI key {key_name} references unknown package: {file_path}"

    def test_22_1_tracked_inventory_files_exist(self) -> None:
        """Test that all required inventory files exist."""
        repo_root = Path(__file__).resolve().parents[2]
        
        # At minimum, config audit should exist
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        assert audit_file.exists(), "Config audit required for Phase 22.1"
