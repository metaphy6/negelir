"""Seed propagation helpers for Phase 11 determinism requirements.

Expose a small helper that applies `cfg.global_seed` to Python's `random`,
NumPy, and (when available) PyTorch vendor RNGs.
"""
from typing import Any

import random


def propagate_global_seed(cfg: Any) -> None:
    """Apply `cfg.global_seed` to common RNG sources.

    This helper is intentionally best-effort: missing optional deps (NumPy,
    PyTorch) are skipped so CPU-only images don't fail.
    """
    seed = int(getattr(cfg, "global_seed", 42))
    random.seed(seed)

    try:
        import numpy as _np

        _np.random.seed(seed)
    except Exception:
        pass

    try:
        import importlib

        torch = importlib.import_module("torch")
        try:
            torch.manual_seed(seed)
            # Best-effort for CUDA devices — no-op if CUDA not available.
            if getattr(torch, "cuda", None):
                try:
                    torch.cuda.manual_seed_all(seed)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        # torch not available — fine for CPU-only images
        pass
