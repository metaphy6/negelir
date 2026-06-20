"""Phase 10 §10.34.2 — Boot-time warm-touch integration.

Integrates model warm-touch into the NLP boot sequence (stage 6+).
Called after models are loaded but before readiness is signaled.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from ai.common.config import cfg
from ai.common.logger import get_logger
from nlp.model_warm_loader import warm_touch_models

logger = get_logger(__name__)


def warm_touch_nlp_models(
    crf_model_path: Optional[str | Path] = None,
    intent_model_path: Optional[str | Path] = None,
    symspell_model_path: Optional[str | Path] = None,
    *,
    clock: Callable[[], float] | None = None,
    cfg_obj: object | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Warm-touch all loaded NLP models at boot time (stage 6+).

    §10.34.2 — CRF/Symspell/Zemberek model warm-mmap: pre-fault models into RAM
    at boot to achieve p99 < 1.5× steady-state on first 100-request burst.

    Args:
        crf_model_path: Path to the CRF model (from cfg.nlp_entity_crf_model_path).
        intent_model_path: Path to the intent model (from cfg.nlp_intent_model_path).
        symspell_model_path: Path to the Symspell model (optional).
        clock: Clock function (for testing).
        cfg_obj: Config object (for testing; defaults to module cfg).

    Returns:
        Tuple of (stats, alerts):
          - stats: dict with warming statistics and metadata
          - alerts: list[dict] of nlp.alert.v1 payloads to publish
    """
    if cfg_obj is None:
        cfg_obj = cfg

    # Respect the warm-touch enable flag
    warm_touch_enabled = getattr(cfg_obj, "nlp_model_warm_touch_enabled", True)
    if not warm_touch_enabled:
        logger.info("Model warm-touch disabled by cfg.nlp_model_warm_touch_enabled")
        return {"enabled": False, "total_pages_warmed": 0, "total_pages_skipped": 0}, []

    # Determine the max-pages cap
    pod_rss_max_mb = getattr(cfg_obj, "nlp_pod_rss_max_mb", 50)
    max_pages = pod_rss_max_mb * 256

    logger.info(
        f"Starting model warm-touch: pod_rss_max_mb={pod_rss_max_mb}, "
        f"max_pages={max_pages}"
    )

    # Call the warm-touch routine
    results, alerts = warm_touch_models(
        crf_model_path=crf_model_path or getattr(cfg_obj, "nlp_entity_crf_model_path", ""),
        intent_model_path=intent_model_path or getattr(cfg_obj, "nlp_intent_model_path", ""),
        symspell_model_path=symspell_model_path,
        max_pages=max_pages,
        clock=clock,
    )

    # Build summary stats
    total_pages_warmed = sum(r.pages_warmed for r in results)
    total_pages_skipped = sum(r.pages_skipped_cap for r in results)
    total_duration_ms = sum(r.duration_ms for r in results)

    stats = {
        "enabled": True,
        "models_processed": len(results),
        "total_pages_warmed": total_pages_warmed,
        "total_pages_skipped": total_pages_skipped,
        "total_duration_ms": total_duration_ms,
        "max_pages_available": max_pages,
        "results": [
            {
                "file_path": str(r.file_path),
                "file_size_bytes": r.file_size_bytes,
                "pages_warmed": r.pages_warmed,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in results
        ],
    }

    if any(r.error for r in results):
        logger.warning(
            f"Some models encountered errors during warm-touch: "
            f"{[r.error for r in results if r.error]}"
        )

    logger.info(
        f"Model warm-touch completed: "
        f"{total_pages_warmed} pages warmed, "
        f"{total_pages_skipped} pages skipped (cap), "
        f"{total_duration_ms:.0f} ms total"
    )

    return stats, alerts


__all__ = ["warm_touch_nlp_models"]
