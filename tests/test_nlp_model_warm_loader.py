"""Tests for Phase 10 §10.34.2 — Model warm-touch infrastructure."""
from __future__ import annotations

import io
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from nlp.model_warm_loader import (
    WarmTouchResult,
    _PAGE_SIZE_BYTES,
    _pages_for_size,
    _warm_touch_file,
    warm_touch_models,
)


class TestWarmTouchBasics:
    """Basic warm-touch functionality tests."""

    def test_pages_for_size_empty(self):
        """Empty file = 0 pages."""
        assert _pages_for_size(0) == 0

    def test_pages_for_size_one_byte(self):
        """One byte = 1 page."""
        assert _pages_for_size(1) == 1

    def test_pages_for_size_full_page(self):
        """Exactly one page size = 1 page."""
        assert _pages_for_size(_PAGE_SIZE_BYTES) == 1

    def test_pages_for_size_partial_second_page(self):
        """One byte into second page = 2 pages."""
        assert _pages_for_size(_PAGE_SIZE_BYTES + 1) == 2

    def test_pages_for_size_large_file(self):
        """100 MB file."""
        file_size = 100 * 1024 * 1024
        pages = _pages_for_size(file_size)
        assert pages == (file_size + _PAGE_SIZE_BYTES - 1) // _PAGE_SIZE_BYTES

    def test_warm_touch_missing_file(self):
        """Warm-touch nonexistent file returns error."""
        nonexistent = Path("/tmp/nonexistent_model_file_xyz.bin")
        result = _warm_touch_file(
            nonexistent,
            max_pages_remaining=[1000],
            clock=time.time,
        )
        assert result.file_size_bytes == 0
        assert result.pages_warmed == 0
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_warm_touch_empty_file(self):
        """Warm-touch empty file returns success with 0 pages warmed."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            result = _warm_touch_file(
                tmp_path,
                max_pages_remaining=[1000],
                clock=time.time,
            )
            assert result.success
            assert result.file_size_bytes == 0
            assert result.pages_warmed == 0
            assert result.pages_skipped_cap == 0
        finally:
            tmp_path.unlink()

    def test_warm_touch_single_page_file(self):
        """Warm-touch a single-page file."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            # Write 1 MB (256 pages)
            tmp.write(b"X" * (256 * _PAGE_SIZE_BYTES))
            tmp_path = Path(tmp.name)

        try:
            result = _warm_touch_file(
                tmp_path,
                max_pages_remaining=[300],
                clock=time.time,
            )
            assert result.success
            assert result.file_size_bytes == 256 * _PAGE_SIZE_BYTES
            assert result.pages_warmed == 256
            assert result.pages_skipped_cap == 0
            assert result.duration_ms >= 0
        finally:
            tmp_path.unlink()

    def test_warm_touch_respects_page_cap(self):
        """Warm-touch respects remaining page cap."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            # Write 2 MB (512 pages)
            tmp.write(b"X" * (512 * _PAGE_SIZE_BYTES))
            tmp_path = Path(tmp.name)

        try:
            # Limit to 256 pages
            max_pages_remaining = [256]
            result = _warm_touch_file(
                tmp_path,
                max_pages_remaining=max_pages_remaining,
                clock=time.time,
            )
            assert result.success
            assert result.file_size_bytes == 512 * _PAGE_SIZE_BYTES
            assert result.pages_warmed == 256
            assert result.pages_skipped_cap == 256
            # After warm-touch, remaining cap should be 0
            assert max_pages_remaining[0] == 0
        finally:
            tmp_path.unlink()

    def test_warm_touch_cap_zero(self):
        """Warm-touch with zero remaining cap."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"X" * (256 * _PAGE_SIZE_BYTES))
            tmp_path = Path(tmp.name)

        try:
            max_pages_remaining = [0]
            result = _warm_touch_file(
                tmp_path,
                max_pages_remaining=max_pages_remaining,
                clock=time.time,
            )
            assert result.success
            assert result.pages_warmed == 0
            assert result.pages_skipped_cap == 256
        finally:
            tmp_path.unlink()


class TestWarmTouchModels:
    """Test the high-level warm_touch_models function."""

    def test_warm_touch_models_no_files(self):
        """warm_touch_models with no model files."""
        results, alerts = warm_touch_models(clock=time.time)
        assert results == []
        assert alerts == []

    def test_warm_touch_models_single_file(self):
        """warm_touch_models with a single model file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp.write(b"MODEL_DATA" * 1024)  # ~10 KB
            tmp_path = Path(tmp.name)

        try:
            results, alerts = warm_touch_models(
                crf_model_path=tmp_path,
                max_pages=1000,
                clock=time.time,
            )
            assert len(results) == 1
            assert results[0].file_path == tmp_path
            assert results[0].success
            assert results[0].pages_warmed > 0
            assert alerts == []
        finally:
            tmp_path.unlink()

    def test_warm_touch_models_multiple_files(self):
        """warm_touch_models with multiple model files."""
        tmp_paths = []
        try:
            # Create 3 temporary files
            for i in range(3):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
                    tmp.write(b"X" * (100 * _PAGE_SIZE_BYTES))
                    tmp_paths.append(Path(tmp.name))

            results, alerts = warm_touch_models(
                crf_model_path=tmp_paths[0],
                intent_model_path=tmp_paths[1],
                symspell_model_path=tmp_paths[2],
                max_pages=1000,
                clock=time.time,
            )
            assert len(results) == 3
            assert all(r.success for r in results)
            assert all(r.pages_warmed > 0 for r in results)
            assert alerts == []
        finally:
            for p in tmp_paths:
                p.unlink()

    def test_warm_touch_models_respects_max_pages(self):
        """warm_touch_models respects the max_pages cap."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            # Create a 500-page file
            tmp.write(b"X" * (500 * _PAGE_SIZE_BYTES))
            tmp_path = Path(tmp.name)

        try:
            # Cap to 256 pages
            results, alerts = warm_touch_models(
                crf_model_path=tmp_path,
                max_pages=256,
                clock=time.time,
            )
            assert len(results) == 1
            assert results[0].pages_warmed == 256
            assert results[0].pages_skipped_cap == 244
            # Expect a cap alert
            assert len(alerts) == 1
            assert alerts[0]["kind"] == "model_warm_touch_capped"
            assert alerts[0]["severity"] == "warn"
            assert "capped" in alerts[0]["reason"].lower()
        finally:
            tmp_path.unlink()

    def test_warm_touch_models_partial_files(self):
        """warm_touch_models with some missing files (graceful degradation)."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"X" * (100 * _PAGE_SIZE_BYTES))
            tmp_path = Path(tmp.name)

        try:
            # CRF exists, intent missing, symspell missing
            results, alerts = warm_touch_models(
                crf_model_path=tmp_path,
                intent_model_path="/nonexistent/intent.bin",
                symspell_model_path="/nonexistent/symspell.bin",
                max_pages=1000,
                clock=time.time,
            )
            # Only the existing CRF file should produce a result
            assert len(results) == 1
            assert results[0].file_path == tmp_path
            assert results[0].success
        finally:
            tmp_path.unlink()

    def test_warm_touch_models_config_max_pages_default(self):
        """warm_touch_models computes max_pages from config when not specified."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"X" * 1024)  # 1 KB
            tmp_path = Path(tmp.name)

        try:
            # When max_pages is None, it should use cfg.nlp_pod_rss_max_mb * 256
            results, alerts = warm_touch_models(crf_model_path=tmp_path)
            assert len(results) == 1
            assert results[0].success
        finally:
            tmp_path.unlink()


class TestWarmTouchResultProperties:
    """Tests for WarmTouchResult dataclass."""

    def test_success_when_no_error(self):
        """WarmTouchResult.success is True when error is None."""
        result = WarmTouchResult(
            file_path=Path("/test"),
            file_size_bytes=1024,
            pages_warmed=1,
            pages_skipped_cap=0,
            duration_ms=10.0,
            error=None,
        )
        assert result.success is True

    def test_success_when_error_present(self):
        """WarmTouchResult.success is False when error is set."""
        result = WarmTouchResult(
            file_path=Path("/test"),
            file_size_bytes=1024,
            pages_warmed=0,
            pages_skipped_cap=0,
            duration_ms=10.0,
            error="Some error",
        )
        assert result.success is False


class TestWarmTouchPlatformCompat:
    """Tests for cross-platform compatibility."""

    def test_warm_touch_works_without_posix_madvise(self):
        """Warm-touch degrades gracefully on platforms without posix_madvise."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"X" * (100 * _PAGE_SIZE_BYTES))
            tmp_path = Path(tmp.name)

        try:
            # Temporarily hide posix_madvise
            original_madvise = getattr(os, "posix_madvise", None)
            if hasattr(os, "posix_madvise"):
                delattr(os, "posix_madvise")

            try:
                result = _warm_touch_file(
                    tmp_path,
                    max_pages_remaining=[1000],
                    clock=time.time,
                )
                # Should still succeed, just without posix_madvise
                assert result.success
                assert result.pages_warmed > 0
            finally:
                # Restore posix_madvise if it was present
                if original_madvise is not None:
                    os.posix_madvise = original_madvise
        finally:
            tmp_path.unlink()


class TestWarmTouchPerformance:
    """Performance-related tests."""

    def test_warm_touch_duration_reasonable(self):
        """Warm-touch completes in reasonable time (< 5 seconds for 1 MB)."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            # 1 MB file
            tmp.write(b"X" * (1024 * 1024))
            tmp_path = Path(tmp.name)

        try:
            result = _warm_touch_file(
                tmp_path,
                max_pages_remaining=[100000],
                clock=time.time,
            )
            assert result.success
            # Should complete in < 5 seconds
            assert result.duration_ms < 5000
        finally:
            tmp_path.unlink()

    def test_warm_touch_does_not_allocate_excessively(self):
        """Warm-touch does not allocate excessive additional memory."""
        # This is a smoke test; actual memory profiling is better in CI.
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"X" * (10 * 1024 * 1024))  # 10 MB
            tmp_path = Path(tmp.name)

        try:
            results, alerts = warm_touch_models(
                crf_model_path=tmp_path,
                max_pages=100000,
                clock=time.time,
            )
            assert results[0].success
        finally:
            tmp_path.unlink()


__all__ = []
