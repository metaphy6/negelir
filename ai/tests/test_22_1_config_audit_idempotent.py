"""Phase 22.1 — Config audit idempotency test."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.phase22
class TestConfigAuditIdempotent:
    """Verify that config audit is idempotent."""

    def test_22_1_config_audit_is_idempotent(self) -> None:
        """Test that running config audit twice produces identical output."""
        repo_root = Path(__file__).resolve().parents[2]
        script_path = repo_root / "xops" / "lint" / "phase22_config_audit.py"
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        # Run the script once
        result1 = subprocess.run(
            ["python3", str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        assert result1.returncode == 0, f"Script failed: {result1.stderr}"
        
        # Read the output
        with open(audit_file, "r", encoding="utf-8") as f:
            data1 = json.load(f)
        hash1 = data1.get("content_hash")
        
        # Run the script again
        result2 = subprocess.run(
            ["python3", str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        assert result2.returncode == 0, f"Script failed: {result2.stderr}"
        
        # Read the output again
        with open(audit_file, "r", encoding="utf-8") as f:
            data2 = json.load(f)
        hash2 = data2.get("content_hash")
        
        # Verify that content hashes match
        assert hash1 == hash2, f"Content hash mismatch: {hash1} != {hash2}"
        
        # Verify that the main counts are the same
        assert data1["total_config_keys"] == data2["total_config_keys"]
        assert data1["ai_config_keys"] == data2["ai_config_keys"]
        assert data1["non_ai_config_keys"] == data2["non_ai_config_keys"]

    def test_22_1_config_audit_content_hash_is_deterministic(self) -> None:
        """Test that the content hash is deterministic."""
        repo_root = Path(__file__).resolve().parents[2]
        audit_file = repo_root / "docs" / "tracking" / "phase22_config_audit.json"
        
        # Load the audit data
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Extract the content hash
        content_hash = data.get("content_hash")
        assert content_hash is not None, "No content_hash in audit file"
        assert isinstance(content_hash, str), "content_hash should be a string"
        assert len(content_hash) == 8, f"content_hash should be 8 chars, got {len(content_hash)}"
        
        # Verify by recomputing the hash
        ai_keys = data["ai_keys"]
        non_ai_keys = data["non_ai_keys"]
        
        content_str = json.dumps({
            "ai_keys": ai_keys,
            "non_ai_keys": non_ai_keys,
        }, sort_keys=True)
        
        recomputed_hash = hashlib.sha256(content_str.encode()).hexdigest()[:8]
        assert recomputed_hash == content_hash, \
            f"Hash mismatch: computed {recomputed_hash}, expected {content_hash}"
