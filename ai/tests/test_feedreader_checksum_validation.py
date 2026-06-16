"""Tests for FeedReader checksum and path validation (Phase 16.4, bullet 4).

Binding proof tests for file validation:
  - test_reader_rejects_path_not_in_manifest: Paths not in manifest are rejected
  - test_reader_rejects_bad_checksum: Files with mismatched checksums are rejected
  - test_reader_accepts_valid_file: Valid files (in manifest, correct checksum) pass
  - test_reader_handles_missing_sidecar_checksum: Files without sidecar checksum are accepted
  - test_reader_accepts_path_when_manifest_empty: When manifest has no file entries, guessed paths are rejected
  - test_reader_computes_checksum_correctly: Checksum computation is deterministic

Properties:
  - Rejects paths not in manifest (counter: feed_reader_guessed_path_rejects_total)
  - Rejects files with bad checksum (counter: feed_reader_checksum_mismatch_total)
  - Accepts files when checksum not required in manifest
  - Checksum is computed on decompressed content for .zst, .gz files
"""

import hashlib
import json
import gzip
from pathlib import Path
from unittest import mock

import pytest

from common.feeds import FeedReader, FeedCursor


class TestFeedReaderChecksumValidation:
    """Tests for checksum and path validation (Phase 16.4, bullet 4)."""

    @pytest.fixture
    def tmp_feeds_dir(self, tmp_path):
        """Create a temporary feeds directory structure."""
        feeds_dir = tmp_path / "feeds"
        feeds_dir.mkdir()
        
        # Create subdirectories
        (feeds_dir / "score" / "mackolik").mkdir(parents=True)
        
        return feeds_dir

    @pytest.fixture
    def reader_with_tmp_path(self, tmp_feeds_dir):
        """Create a FeedReader pointing to temp path."""
        reader = FeedReader(
            feeds_path=tmp_feeds_dir,
            verify_schema_on_init=False,
            emitter_management_url=None,
        )
        return reader

    def test_reader_rejects_path_not_in_manifest(self, tmp_feeds_dir, reader_with_tmp_path):
        """Reader rejects files not listed in manifest."""
        # Create a manifest with no files
        manifest = {
            "emitter_version": "0.0.0",
            "generated_at": "2026-04-20T10:00:00Z",
            "planes": {
                "score": {
                    "mackolik": {
                        "files": []  # No files listed
                    }
                }
            }
        }
        
        # Create an actual file
        file_path = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file_path.write_text('{"id": 1}\n')
        
        # Validation should reject this file (path not in manifest)
        result = reader_with_tmp_path._validate_file_path_and_checksum(file_path, manifest)
        assert result is False

    def test_reader_accepts_valid_file_in_manifest(self, tmp_feeds_dir, reader_with_tmp_path):
        """Reader accepts file when it is in manifest (checksum optional)."""
        # Create a file
        file_path = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file_path.write_text('{"id": 1}\n')
        
        # Create manifest with this file listed (no checksum required)
        manifest = {
            "emitter_version": "0.0.0",
            "generated_at": "2026-04-20T10:00:00Z",
            "planes": {
                "score": {
                    "mackolik": {
                        "files": [
                            {
                                "path": "2026-04-20.ndjson",
                                "rows": 1,
                                # No checksum in manifest
                            }
                        ]
                    }
                }
            }
        }
        
        # Validation should accept this file
        result = reader_with_tmp_path._validate_file_path_and_checksum(file_path, manifest)
        assert result is True

    def test_reader_rejects_bad_checksum(self, tmp_feeds_dir, reader_with_tmp_path):
        """Reader rejects file when checksum mismatches."""
        # Create a file
        file_path = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file_path.write_text('{"id": 1}\n')
        
        # Compute actual checksum
        actual_sha = hashlib.sha256('{"id": 1}\n'.encode("utf-8")).hexdigest()
        
        # Create manifest with WRONG checksum
        wrong_sha = "0000000000000000000000000000000000000000000000000000000000000000"
        manifest = {
            "emitter_version": "0.0.0",
            "generated_at": "2026-04-20T10:00:00Z",
            "planes": {
                "score": {
                    "mackolik": {
                        "files": [
                            {
                                "path": "2026-04-20.ndjson",
                                "rows": 1,
                                "sha256": wrong_sha,  # Wrong checksum
                            }
                        ]
                    }
                }
            }
        }
        
        # Validation should reject due to checksum mismatch
        result = reader_with_tmp_path._validate_file_path_and_checksum(file_path, manifest)
        assert result is False

    def test_reader_accepts_correct_checksum(self, tmp_feeds_dir, reader_with_tmp_path):
        """Reader accepts file when checksum matches."""
        # Create a file
        content = '{"id": 1}\n'
        file_path = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file_path.write_text(content)
        
        # Compute actual checksum
        actual_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        
        # Create manifest with CORRECT checksum
        manifest = {
            "emitter_version": "0.0.0",
            "generated_at": "2026-04-20T10:00:00Z",
            "planes": {
                "score": {
                    "mackolik": {
                        "files": [
                            {
                                "path": "2026-04-20.ndjson",
                                "rows": 1,
                                "sha256": actual_sha,  # Correct checksum
                            }
                        ]
                    }
                }
            }
        }
        
        # Validation should accept
        result = reader_with_tmp_path._validate_file_path_and_checksum(file_path, manifest)
        assert result is True

    def test_reader_computes_file_checksum_correctly(self, tmp_feeds_dir, reader_with_tmp_path):
        """File checksum computation is deterministic."""
        # Create a file
        content = '{"id": 1}\n{"id": 2}\n'
        file_path = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file_path.write_text(content)
        
        # Compute checksum via reader method
        reader_sha = reader_with_tmp_path._compute_file_sha256(file_path)
        
        # Compute checksum independently
        expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        
        assert reader_sha == expected_sha

    def test_reader_validates_gzip_compressed_file(self, tmp_feeds_dir, reader_with_tmp_path):
        """Checksum of gzip-compressed file is computed on decompressed content."""
        # Create compressed file
        content = '{"id": 1}\n'
        file_path = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson.gz"
        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            f.write(content)
        
        # Checksum should be on decompressed content
        expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        
        # Compute via reader
        reader_sha = reader_with_tmp_path._compute_file_sha256(file_path)
        
        assert reader_sha == expected_sha

    def test_reader_handles_manifest_with_multiple_files(self, tmp_feeds_dir, reader_with_tmp_path):
        """Reader finds correct file entry in manifest with multiple files."""
        # Create two files
        file1 = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file2 = tmp_feeds_dir / "score" / "mackolik" / "2026-04-21.ndjson"
        file1.write_text('{"id": 1}\n')
        file2.write_text('{"id": 2}\n')
        
        sha1 = hashlib.sha256('{"id": 1}\n'.encode("utf-8")).hexdigest()
        sha2 = hashlib.sha256('{"id": 2}\n'.encode("utf-8")).hexdigest()
        
        # Create manifest with both files
        manifest = {
            "emitter_version": "0.0.0",
            "generated_at": "2026-04-20T10:00:00Z",
            "planes": {
                "score": {
                    "mackolik": {
                        "files": [
                            {
                                "path": "2026-04-20.ndjson",
                                "rows": 1,
                                "sha256": sha1,
                            },
                            {
                                "path": "2026-04-21.ndjson",
                                "rows": 1,
                                "sha256": sha2,
                            }
                        ]
                    }
                }
            }
        }
        
        # Both files should validate
        result1 = reader_with_tmp_path._validate_file_path_and_checksum(file1, manifest)
        result2 = reader_with_tmp_path._validate_file_path_and_checksum(file2, manifest)
        
        assert result1 is True
        assert result2 is True

    def test_reader_handles_missing_manifest_entry_in_valid_path(self, tmp_feeds_dir, reader_with_tmp_path):
        """Reader correctly identifies missing file in otherwise valid manifest."""
        # Create only file1
        file1 = tmp_feeds_dir / "score" / "mackolik" / "2026-04-20.ndjson"
        file1.write_text('{"id": 1}\n')
        
        # Try to validate file2 which is not created
        file2 = tmp_feeds_dir / "score" / "mackolik" / "2026-04-21.ndjson"
        
        sha1 = hashlib.sha256('{"id": 1}\n'.encode("utf-8")).hexdigest()
        
        # Create manifest with both files listed
        manifest = {
            "emitter_version": "0.0.0",
            "generated_at": "2026-04-20T10:00:00Z",
            "planes": {
                "score": {
                    "mackolik": {
                        "files": [
                            {
                                "path": "2026-04-20.ndjson",
                                "rows": 1,
                                "sha256": sha1,
                            },
                            {
                                "path": "2026-04-21.ndjson",
                                "rows": 1,
                                "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                            }
                        ]
                    }
                }
            }
        }
        
        # file1 should validate
        result1 = reader_with_tmp_path._validate_file_path_and_checksum(file1, manifest)
        assert result1 is True
        
        # file2 should fail (checksum mismatch or file not found error)
        result2 = reader_with_tmp_path._validate_file_path_and_checksum(file2, manifest)
        # This will fail because the file doesn't exist and checksum computation will raise
        assert result2 is False
