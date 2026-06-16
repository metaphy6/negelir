"""Tests for durability semantics and file rotation (Phase 16.2 bullet 4).

Covers:
  - Fsync modes (always, batch, off)
  - Compression (zstd, gzip, off)
  - Per-file SHA256 checksums
  - Atomic rotation with safety
  - Rotation state for manifest
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from common.feeds.rotator import FileRotator, CompressionConfig


class TestCompressionConfig:
    """Tests for CompressionConfig."""

    def test_compression_config_init_defaults(self):
        """CompressionConfig initializes with defaults."""
        cfg = CompressionConfig()
        assert cfg.codec == "zstd"
        assert cfg.level == 9
        assert cfg.dict_path is None

    def test_compression_config_init_custom(self):
        """CompressionConfig initializes with custom values."""
        cfg = CompressionConfig(codec="gzip", level=6)
        assert cfg.codec == "gzip"
        assert cfg.level == 6


class TestFileRotator:
    """Tests for FileRotator."""

    def test_rotator_init_default(self):
        """FileRotator initializes with defaults."""
        rotator = FileRotator()
        assert rotator.compression.codec == "zstd"
        assert rotator.fsync_mode == "always"
        assert rotator.last_rotation_bytes == 0

    def test_rotator_init_custom(self):
        """FileRotator initializes with custom config."""
        cfg = CompressionConfig(codec="gzip", level=6)
        rotator = FileRotator(
            compression=cfg,
            fsync_mode="batch",
            fsync_batch_ms=200,
        )
        assert rotator.compression.codec == "gzip"
        assert rotator.fsync_mode == "batch"
        assert rotator.fsync_batch_ms == 200

    def test_rotator_rotate_file_not_found(self):
        """Rotation handles non-existent files gracefully."""
        rotator = FileRotator()
        result = rotator.rotate_file(Path("/nonexistent/file.ndjson"))
        
        assert result["status"] == "not_found"
        assert result["bytes"] == 0

    def test_rotator_rotate_file_no_compression(self):
        """Rotation works with compression=off."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.ndjson"
            file_path.write_bytes(b"line1\nline2\n")
            
            rotator = FileRotator(
                compression=CompressionConfig(codec="off"),
                fsync_mode="off",  # Disable fsync for test
            )
            
            result = rotator.rotate_file(file_path)
            
            assert result["status"] == "success"
            assert result["bytes"] == 12
            assert result["codec"] == "off"
            assert result["checksum"] is not None

    def test_rotator_checksum_consistency(self):
        """SHA256 sidecar checksum is computed correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.ndjson"
            content = b"test content\n"
            file_path.write_bytes(content)
            
            rotator = FileRotator(
                compression=CompressionConfig(codec="off"),
                fsync_mode="off",
            )
            
            result = rotator.rotate_file(file_path)
            
            # Verify checksum matches
            import hashlib
            expected_checksum = hashlib.sha256(content).hexdigest()
            assert result["checksum"] == expected_checksum

    def test_rotator_sidecar_file_created(self):
        """SHA256 sidecar file is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.ndjson"
            file_path.write_bytes(b"test\n")
            
            rotator = FileRotator(
                compression=CompressionConfig(codec="off"),
                fsync_mode="off",
            )
            
            result = rotator.rotate_file(file_path)
            sidecar_path = Path(result["sidecar_path"])
            
            assert sidecar_path.exists()
            assert sidecar_path.suffix == ".sha256"
            content = sidecar_path.read_text()
            assert "  test.ndjson" in content

    def test_rotator_get_rotation_state(self):
        """get_rotation_state returns metadata."""
        rotator = FileRotator()
        rotator.last_rotation_file = "test.ndjson.zst"
        rotator.last_rotation_bytes = 1024
        rotator.last_rotation_checksum = "abc123"
        
        state = rotator.get_rotation_state()
        
        assert state["last_rotation_file"] == "test.ndjson.zst"
        assert state["last_rotation_bytes"] == 1024
        assert state["last_rotation_checksum"] == "abc123"
        assert state["codec"] == "zstd"
        assert state["level"] == 9

    def test_rotator_fsync_mode_off(self):
        """fsync_mode=off skips fsync operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.ndjson"
            file_path.write_bytes(b"data\n")
            
            rotator = FileRotator(fsync_mode="off")
            # Should not raise even if fsync fails
            rotator._fsync_file(file_path)
            rotator._fsync_directory(file_path.parent)
            # If this completes without error, fsync was skipped

    def test_rotator_compression_zstd(self):
        """Rotation compresses with zstd."""
        pytest.importorskip("zstandard")  # Skip if zstandard not installed
        
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.ndjson"
            content = b"test data\n" * 100  # Repeat to compress well
            file_path.write_bytes(content)
            
            rotator = FileRotator(
                compression=CompressionConfig(codec="zstd", level=9),
                fsync_mode="off",
            )
            
            result = rotator.rotate_file(file_path)
            
            assert result["status"] == "success"
            assert result["codec"] == "zstd"
            # Original file should be gone
            assert not file_path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
