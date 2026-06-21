"""Small numerical helpers used by Phase 11 inference guards.

Provide a best-effort PMF validator that checks finiteness, range, and
sum-to-one within a tolerance.
"""
from typing import Iterable

import math


def is_valid_pmf(probs: Iterable[float], eps: float = 1e-6) -> bool:
    vals = list(probs)
    if not vals:
        return False
    for v in vals:
        if not math.isfinite(v):
            return False
        if v < 0.0 or v > 1.0:
            return False
    s = sum(vals)
    return abs(s - 1.0) <= eps
