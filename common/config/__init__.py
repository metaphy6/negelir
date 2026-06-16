"""Phase 18 transitional config layer.

During Phase 18, this is a compatibility shim that re-exports the legacy
ai/common/config for all imports. The actual Config class with validate()
method lives in ai/common/config.py.

Phase 22+: This file becomes canonical when the physical move to root/common
happens and ai/ tree is deleted.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Force import from ai/common/config by using full module path
if 'ai.common.config' not in sys.modules:
    # Add ai to path if not already there
    repo_root = Path(__file__).resolve().parent.parent.parent
    ai_path = str(repo_root / "ai")
    if ai_path not in sys.path:
        sys.path.insert(0, ai_path)

# Import using the full path to avoid ambiguity
import ai.common.config as _impl

# Re-export everything from ai.common.config
Config = _impl.Config
cfg = _impl.cfg

__all__ = ["Config", "cfg"]
