"""Phase 10 §10.34.2 — Model warm-mmap (pre-faulting) infrastructure.

Loads CRF, Symspell, and intent models into memory on boot to eliminate
page-fault latency spikes on first request. Uses os.posix_madvise(MADV_WILLNEED)
and 1-byte read per page to warm the mmap regions.

Responsibilities:
  * Warm-touch all loaded model files (CRF, Symspell, intent)
  * Cap warm-touch to nlp_pod_rss_max_mb * 256 pages to avoid OOM on small pods
  * Emit alerts when cap is exceeded
  * Provide async/sync interfaces for boot integration
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from common.config import cfg
from common.logger import get_logger

logger = get_logger(__name__)

# Page size in bytes (typical on Linux x86_64)
_PAGE_SIZE_BYTES = 4096

# Capability to use posix_madvise (MADV_WILLNEED)
# Not available on all platforms (e.g., macOS). On Windows, posix_madvise is unavailable.
_POSIX_MADVISE_AVAILABLE = hasattr(os, "posix_madvise")
_MADV_WILLNEED = getattr(os, "MADV_WILLNEED", None)


@dataclass(frozen=True)
class WarmTouchResult:
    """Result of a warm-touch operation on a single model file."""

    file_path: Path
    file_size_bytes: int
    pages_warmed: int
    pages_skipped_cap: int
    duration_ms: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """True if the warm-touch completed without error."""
        return self.error is None


def _pages_for_size(size_bytes: int) -> int:
    """Compute the number of 4KB pages needed for a file."""
    return (size_bytes + _PAGE_SIZE_BYTES - 1) // _PAGE_SIZE_BYTES


def _warm_touch_file(
    model_path: Path,
    *,
    max_pages_remaining: list[int],
    clock: Callable[[], float],
) -> WarmTouchResult:
    """Warm-touch a single model file by pre-faulting its pages.

    Args:
        model_path: Path to the model file to warm.
        max_pages_remaining: Mutable list with a single element: the page cap remaining.
            Updated in-place to track consumption.
        clock: Callable returning the current time in seconds (e.g., time.time).

    Returns:
        WarmTouchResult with statistics and any error encountered.
    """
    start_s = clock()

    # Check if the file exists and is readable.
    if not model_path.exists():
        return WarmTouchResult(
            file_path=model_path,
            file_size_bytes=0,
            pages_warmed=0,
            pages_skipped_cap=0,
            duration_ms=(clock() - start_s) * 1000,
            error=f"File not found: {model_path}",
        )

    try:
        file_size_bytes = model_path.stat().st_size
    except OSError as e:
        return WarmTouchResult(
            file_path=model_path,
            file_size_bytes=0,
            pages_warmed=0,
            pages_skipped_cap=0,
            duration_ms=(clock() - start_s) * 1000,
            error=f"stat failed: {e}",
        )

    if file_size_bytes == 0:
        return WarmTouchResult(
            file_path=model_path,
            file_size_bytes=0,
            pages_warmed=0,
            pages_skipped_cap=0,
            duration_ms=(clock() - start_s) * 1000,
        )

    total_pages = _pages_for_size(file_size_bytes)
    pages_to_warm = min(total_pages, max_pages_remaining[0])
    pages_skipped_cap = total_pages - pages_to_warm

    if pages_to_warm == 0:
        return WarmTouchResult(
            file_path=model_path,
            file_size_bytes=file_size_bytes,
            pages_warmed=0,
            pages_skipped_cap=pages_skipped_cap,
            duration_ms=(clock() - start_s) * 1000,
        )

    # Open the file and warm-touch pages.
    try:
        with open(model_path, "rb") as f:
            # If posix_madvise is available, tell the OS we'll need these pages soon.
            if _POSIX_MADVISE_AVAILABLE and _MADV_WILLNEED is not None:
                try:
                    os.posix_madvise(
                        f.fileno(),
                        0,  # offset
                        pages_to_warm * _PAGE_SIZE_BYTES,
                        _MADV_WILLNEED,
                    )
                except (OSError, NotImplementedError) as e:
                    # posix_madvise may not be implemented on this platform,
                    # but we can still warm via read().
                    logger.debug(f"posix_madvise failed (continuing with read): {e}")

            # Read 1 byte from each page to trigger a fault and load the page into RAM.
            for page_idx in range(pages_to_warm):
                offset = page_idx * _PAGE_SIZE_BYTES
                try:
                    f.seek(offset)
                    _ = f.read(1)  # noqa: F841 (intentional dummy read to warm page)
                except OSError as e:
                    return WarmTouchResult(
                        file_path=model_path,
                        file_size_bytes=file_size_bytes,
                        pages_warmed=page_idx,
                        pages_skipped_cap=pages_skipped_cap,
                        duration_ms=(clock() - start_s) * 1000,
                        error=f"Read failed at page {page_idx}: {e}",
                    )

    except OSError as e:
        return WarmTouchResult(
            file_path=model_path,
            file_size_bytes=file_size_bytes,
            pages_warmed=0,
            pages_skipped_cap=pages_skipped_cap,
            duration_ms=(clock() - start_s) * 1000,
            error=f"Failed to open model file: {e}",
        )

    # Update remaining page cap.
    max_pages_remaining[0] -= pages_to_warm

    return WarmTouchResult(
        file_path=model_path,
        file_size_bytes=file_size_bytes,
        pages_warmed=pages_to_warm,
        pages_skipped_cap=pages_skipped_cap,
        duration_ms=(clock() - start_s) * 1000,
    )


def warm_touch_models(
    crf_model_path: Optional[Path | str] = None,
    intent_model_path: Optional[Path | str] = None,
    symspell_model_path: Optional[Path | str] = None,
    *,
    max_pages: Optional[int] = None,
    clock: Callable[[], float] = None,
) -> tuple[list[WarmTouchResult], list[dict[str, Any]]]:
    """Warm-touch all loaded NLP models to eliminate page-fault latency on first request.

    §10.34.2 — CRF/Symspell/Zemberek model warm-mmap: pre-fault models into RAM
    at boot to achieve p99 < 1.5× steady-state on first 100-request burst.

    Args:
        crf_model_path: Path to the CRF model file (e.g., from cfg.nlp_entity_crf_model_path).
        intent_model_path: Path to the intent model file (fastText binary).
        symspell_model_path: Path to the Symspell dictionary or model file (optional for now).
        max_pages: Hard cap on total pages to warm. If None, computed as
            cfg.nlp_pod_rss_max_mb * 256. On cap exceeded, emit alerts.
        clock: Callable returning current time (e.g., time.time). For testing.

    Returns:
        Tuple of (results, alerts):
          - results: list[WarmTouchResult] — per-model warm-touch statistics
          - alerts: list[dict] — nlp.alert.v1 payloads for cap-exceeded cases
    """
    import time

    if clock is None:
        clock = time.time

    # Compute the page cap (§10.34.2).
    if max_pages is None:
        max_pages = cfg.nlp_pod_rss_max_mb * 256

    # Collect model paths to warm.
    model_paths: list[Path] = []
    for path in (crf_model_path, intent_model_path, symspell_model_path):
        if path:
            p = Path(path)
            if p.exists():
                model_paths.append(p)

    # Warm-touch models in order.
    results: list[WarmTouchResult] = []
    alerts: list[dict[str, Any]] = []
    max_pages_remaining = [max_pages]

    for model_path in model_paths:
        result = _warm_touch_file(
            model_path,
            max_pages_remaining=max_pages_remaining,
            clock=clock,
        )
        results.append(result)

        if result.error:
            logger.warning(f"Model warm-touch failed for {model_path}: {result.error}")

    # Check if we hit the cap on any model.
    if any(r.pages_skipped_cap > 0 for r in results):
        total_skipped = sum(r.pages_skipped_cap for r in results)
        alerts.append({
            "topic": "nlp.alert.v1",
            "kind": "model_warm_touch_capped",
            "severity": "warn",
            "producer": "nlp.model_warm_loader",
            "reason": (
                f"Model warm-touch capped: {total_skipped} pages skipped due to "
                f"max_pages limit ({max_pages}). Warm-touch is a perf optimization "
                "only; correctness unaffected."
            ),
            "details": {
                "max_pages_available": max_pages,
                "max_pages_skipped": total_skipped,
                "pod_rss_max_mb": cfg.nlp_pod_rss_max_mb,
            },
        })

    return results, alerts


__all__ = ["warm_touch_models", "WarmTouchResult"]
