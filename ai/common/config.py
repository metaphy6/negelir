"""Phase 22.3 config merge: backward-compatibility shim.

The canonical Config implementation lives in common/config/ai_pipeline.py.
This file re-exports it for backward compatibility during the Phase 18→Phase 22 transition.
"""

from common.config.ai_pipeline import Config, cfg

__all__ = ["Config", "cfg"]
