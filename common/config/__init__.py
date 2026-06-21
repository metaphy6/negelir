"""Phase 22.3 config merge: ai-authoritative shim.

The canonical Config implementation lives in common/config/ai_pipeline.py.
This file re-exports it for backward compatibility.
"""
from __future__ import annotations

# Import directly from ai_pipeline (the new canonical location)
from common.config.ai_pipeline import Config, cfg

__all__ = ["Config", "cfg"]
