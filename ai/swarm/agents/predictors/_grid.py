"""Shared score-grid math for predictors that emit one.

Phase 5 deduplication: Dixon-Coles and the xG predictor both built
their own ``_score_grid`` + ``_poisson`` helpers, each calling
``math.factorial`` once per cell of an 81-cell matrix (and four times
again to project markets). This module hosts the *single* Poisson +
grid + market-projection implementation they share.

Performance notes
-----------------

* ``poisson_pmf`` uses the recurrence ``P(k) = P(k-1) · λ / k``
  instead of ``exp(-λ) · λ^k / k!``. That drops factorial calls
  entirely (one ``math.exp`` per call instead of ``MAX_GOALS²``
  factorials per grid).
* ``score_grid`` builds the joint matrix as a list-of-lists once;
  the caller projects 1X2 / AH / OU / BTTS off it directly.
* Market projections use precomputed row sums so each lives in O(N)
  instead of the O(N²) double-comprehensions the predictors used to
  copy-paste.

These helpers are the only score-grid builders in Phase 5; the
``cpu_only`` parity test exercises them indirectly via the
predictors.
"""
from __future__ import annotations

import math
from typing import Sequence

# 8 goals per side covers >99.9% of football match probability mass
# (same constant the legacy DC + XGB-xG modules used).
MAX_GOALS: int = 8


def poisson_pmf(lam: float, max_k: int = MAX_GOALS) -> list[float]:
    """Return ``[P(0), P(1), …, P(max_k)]`` for a Poisson(λ).

    Uses the recurrence ``P(k) = P(k-1) · λ / k`` so we only call
    ``math.exp`` once. Hot path; callers project markets straight off
    the returned list.
    """
    if lam <= 0.0:
        out = [0.0] * (max_k + 1)
        out[0] = 1.0
        return out
    out = [0.0] * (max_k + 1)
    p = math.exp(-lam)
    out[0] = p
    for k in range(1, max_k + 1):
        p = p * lam / k
        out[k] = p
    return out


def _dc_correction(h: int, a: int, lam_h: float, lam_a: float, rho: float) -> float:
    """Dixon-Coles low-score adjustment τ(h, a)."""
    if h == 0 and a == 0:
        return 1.0 - lam_h * lam_a * rho
    if h == 0 and a == 1:
        return 1.0 + lam_h * rho
    if h == 1 and a == 0:
        return 1.0 + lam_a * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def score_grid(
    lam_h: float,
    lam_a: float,
    *,
    dc_rho: float | None = None,
    max_goals: int = MAX_GOALS,
) -> list[list[float]]:
    """Joint score probability matrix for two Poissons.

    When ``dc_rho`` is given (``DixonColesPredictor``), the
    Dixon-Coles low-score correction is applied to {0-0, 1-0, 0-1,
    1-1}; otherwise the matrix is the independent product
    (``XgbXgPredictor``).
    """
    h_pmf = poisson_pmf(lam_h, max_goals)
    a_pmf = poisson_pmf(lam_a, max_goals)
    grid = [[0.0] * (max_goals + 1) for _ in range(max_goals + 1)]
    total = 0.0
    if dc_rho is None:
        # Pure outer product. Avoids the per-cell branch of the DC path.
        for h in range(max_goals + 1):
            ph = h_pmf[h]
            row = grid[h]
            for a in range(max_goals + 1):
                v = ph * a_pmf[a]
                row[a] = v
                total += v
    else:
        for h in range(max_goals + 1):
            ph = h_pmf[h]
            row = grid[h]
            for a in range(max_goals + 1):
                v = ph * a_pmf[a] * _dc_correction(h, a, lam_h, lam_a, dc_rho)
                if v < 0.0:
                    v = 0.0
                row[a] = v
                total += v
    if total > 0.0:
        inv = 1.0 / total
        for h in range(max_goals + 1):
            row = grid[h]
            for a in range(max_goals + 1):
                row[a] *= inv
    return grid


# ── Market projections ──────────────────────────────────────────


def project_1x2(grid: Sequence[Sequence[float]]) -> dict[str, float]:
    """1X2 projection over a square score grid."""
    n = len(grid)
    p_h = 0.0
    p_d = 0.0
    for h in range(n):
        row = grid[h]
        for a in range(h):
            p_h += row[a]
        p_d += row[h]
    p_a = max(0.0, 1.0 - p_h - p_d)
    return {"H": p_h, "D": p_d, "A": p_a}


def project_ah_home(grid: Sequence[Sequence[float]]) -> dict[str, float]:
    """Asian-handicap home (h-0.5) — same as 'home wins outright'."""
    n = len(grid)
    p_home = 0.0
    for h in range(n):
        row = grid[h]
        for a in range(h):
            p_home += row[a]
    return {"home": p_home, "away": max(0.0, 1.0 - p_home)}


def project_ou25(grid: Sequence[Sequence[float]]) -> dict[str, float]:
    """Over/Under 2.5 goals: cells with h + a >= 3."""
    n = len(grid)
    over = 0.0
    for h in range(n):
        row = grid[h]
        # threshold a-index for h+a >= 3 ⇒ a >= 3 - h
        a_lo = max(0, 3 - h)
        for a in range(a_lo, n):
            over += row[a]
    return {"over": over, "under": max(0.0, 1.0 - over)}


def project_btts(grid: Sequence[Sequence[float]]) -> dict[str, float]:
    """Both teams to score: h >= 1 AND a >= 1."""
    n = len(grid)
    yes = 0.0
    for h in range(1, n):
        row = grid[h]
        for a in range(1, n):
            yes += row[a]
    return {"yes": yes, "no": max(0.0, 1.0 - yes)}


def modal_mass(grid: Sequence[Sequence[float]]) -> float:
    """Probability mass on the most likely cell — used as a
    confidence proxy by score-grid predictors."""
    return max(max(row) for row in grid)


__all__ = [
    "MAX_GOALS",
    "modal_mass",
    "poisson_pmf",
    "project_1x2",
    "project_ah_home",
    "project_btts",
    "project_ou25",
    "score_grid",
]
