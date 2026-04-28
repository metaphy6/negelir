"""`pred.xgb_xg.v1` — xG / shot-quality predictor.

Phase 5 ships the agent surface; the trainer (Phase 5.4) populates a
real booster later. Until then a deterministic logistic over xG-style
features keeps the swarm voting. Produces a score grid via
independent Poissons of the predicted xG, so consensus's score-grid
sanity check has two contributors (this + Dixon-Coles).

Features (defaults are league-neutral):
  * ``home_xg_per_match`` (default 1.4)
  * ``away_xg_per_match`` (default 1.1)
  * ``home_shot_quality`` (default 0.10)  — xG per shot
  * ``away_shot_quality`` (default 0.09)
  * ``home_advantage`` (default 0.10)     — added to home_xg
"""
from __future__ import annotations

import math
from typing import Any

from ._base import PredictorAgent, PredictorContext

_MAX_GOALS = 8
_DEFAULT_HOME_XG = 1.4
_DEFAULT_AWAY_XG = 1.1
_DEFAULT_HOME_SHOT_Q = 0.10
_DEFAULT_AWAY_SHOT_Q = 0.09
_DEFAULT_HA = 0.10


def _poisson(lam: float, k: int) -> float:
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _independent_grid(lam_h: float, lam_a: float) -> list[list[float]]:
    grid = [[0.0] * (_MAX_GOALS + 1) for _ in range(_MAX_GOALS + 1)]
    total = 0.0
    for h in range(_MAX_GOALS + 1):
        ph = _poisson(lam_h, h)
        for a in range(_MAX_GOALS + 1):
            v = ph * _poisson(lam_a, a)
            grid[h][a] = v
            total += v
    if total > 0.0:
        for h in range(_MAX_GOALS + 1):
            for a in range(_MAX_GOALS + 1):
                grid[h][a] /= total
    return grid


class XgbXgPredictor(PredictorAgent):
    predictor_id = "pred.xgb_xg.v1"
    features_version = "xg.v1"

    def __init__(self, *, clock: Any = None, booster: Any = None) -> None:
        super().__init__(clock=clock)
        self._booster = booster

    def load_booster(self, booster: Any) -> None:
        self._booster = booster

    def _expected_goals(self, ctx: PredictorContext) -> tuple[float, float]:
        f = ctx.features
        # Blend per-match xG with shot-quality (a richer xG would be
        # shots × shot_quality; we mix them to differentiate from the
        # Dixon-Coles predictor's pure xG inputs).
        home_xg = float(f.get("home_xg_per_match", _DEFAULT_HOME_XG))
        away_xg = float(f.get("away_xg_per_match", _DEFAULT_AWAY_XG))
        home_q = float(f.get("home_shot_quality", _DEFAULT_HOME_SHOT_Q))
        away_q = float(f.get("away_shot_quality", _DEFAULT_AWAY_SHOT_Q))
        ha = float(f.get("home_advantage", _DEFAULT_HA))
        # Penalize low shot quality slightly; reward high.
        lam_h = max(0.05, home_xg * (1.0 + 2.0 * (home_q - 0.10)) + ha)
        lam_a = max(0.05, away_xg * (1.0 + 2.0 * (away_q - 0.10)))
        return lam_h, lam_a

    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        lam_h, lam_a = self._expected_goals(ctx)
        grid = _independent_grid(lam_h, lam_a)
        modal = max(max(row) for row in grid)
        confidence = max(0.05, min(1.0, modal * 4.0))

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
