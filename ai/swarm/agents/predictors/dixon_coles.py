"""`pred.dixon_coles.v1` — bivariate Poisson with low-score correction.

Computes a score grid up to ``_MAX_GOALS`` using two independent
Poissons (home_xg, away_xg) plus the Dixon-Coles ρ low-score
adjustment for {0-0, 1-0, 0-1, 1-1}. The grid is the canonical
output; market projections (1X2, AH, OU2.5, BTTS) sum cells.

Features (with sane defaults so unit tests don't need a feature
store):

  * ``home_xg`` (default 1.4)
  * ``away_xg`` (default 1.1)
  * ``dixon_coles_rho`` (default -0.10)
"""
from __future__ import annotations

import math
from typing import Any

from ._base import PredictorAgent, PredictorContext

# 8 goals per side covers >99.9% of football match probability mass.
_MAX_GOALS = 8
_DEFAULT_HOME_XG = 1.4
_DEFAULT_AWAY_XG = 1.1
_DEFAULT_RHO = -0.10
# Confidence proxy: how concentrated the score grid is. We use the
# probability mass on the modal cell; higher mass ⇒ more decisive.
_CONFIDENCE_MODAL_FLOOR = 0.05


def _poisson(lam: float, k: int) -> float:
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


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


def _score_grid(lam_h: float, lam_a: float, rho: float) -> list[list[float]]:
    grid = [[0.0] * (_MAX_GOALS + 1) for _ in range(_MAX_GOALS + 1)]
    total = 0.0
    for h in range(_MAX_GOALS + 1):
        for a in range(_MAX_GOALS + 1):
            p = _poisson(lam_h, h) * _poisson(lam_a, a) * _dc_correction(h, a, lam_h, lam_a, rho)
            p = max(p, 0.0)
            grid[h][a] = p
            total += p
    if total > 0.0:
        for h in range(_MAX_GOALS + 1):
            for a in range(_MAX_GOALS + 1):
                grid[h][a] /= total
    return grid


class DixonColesPredictor(PredictorAgent):
    predictor_id = "pred.dixon_coles.v1"

    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        f = ctx.features
        lam_h = max(0.05, float(f.get("home_xg", _DEFAULT_HOME_XG)))
        lam_a = max(0.05, float(f.get("away_xg", _DEFAULT_AWAY_XG)))
        rho = float(f.get("dixon_coles_rho", _DEFAULT_RHO))

        grid = _score_grid(lam_h, lam_a, rho)
        modal = max(max(row) for row in grid)
        confidence = max(_CONFIDENCE_MODAL_FLOOR, min(1.0, modal * 4.0))

        market = ctx.request.market
        if market == "1x2":
            p_h = sum(grid[h][a] for h in range(_MAX_GOALS + 1) for a in range(h))
            p_d = sum(grid[i][i] for i in range(_MAX_GOALS + 1))
            p_a = max(0.0, 1.0 - p_h - p_d)
            outcomes = {"H": p_h, "D": p_d, "A": p_a}
        elif market == "ah":
            p_home = sum(grid[h][a] for h in range(_MAX_GOALS + 1) for a in range(h))
            outcomes = {"home": p_home, "away": max(0.0, 1.0 - p_home)}
        elif market == "ou_2_5":
            over = sum(
                grid[h][a]
                for h in range(_MAX_GOALS + 1)
                for a in range(_MAX_GOALS + 1)
                if h + a >= 3
            )
            outcomes = {"over": over, "under": max(0.0, 1.0 - over)}
        elif market == "btts":
            yes = sum(
                grid[h][a]
                for h in range(1, _MAX_GOALS + 1)
                for a in range(1, _MAX_GOALS + 1)
            )
            outcomes = {"yes": yes, "no": max(0.0, 1.0 - yes)}
        else:
            return ({"market_outcomes": {}}, 0.0)

        return (
            {"market_outcomes": outcomes, "score_grid": grid},
            confidence,
        )
