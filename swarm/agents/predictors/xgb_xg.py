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

from typing import Any

from ._base import PredictorAgent, PredictorContext
from ._grid import (
    modal_mass,
    project_1x2,
    project_ah_home,
    project_btts,
    project_ou25,
    score_grid,
)

_DEFAULT_HOME_XG = 1.4
_DEFAULT_AWAY_XG = 1.1
_DEFAULT_HOME_SHOT_Q = 0.10
_DEFAULT_AWAY_SHOT_Q = 0.09
_DEFAULT_HA = 0.10
_CONFIDENCE_MODAL_FLOOR = 0.05


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
        grid = score_grid(lam_h, lam_a)  # independent (no DC ρ)
        confidence = max(_CONFIDENCE_MODAL_FLOOR, min(1.0, modal_mass(grid) * 4.0))

        market = ctx.request.market
        if market == "1x2":
            outcomes = project_1x2(grid)
        elif market == "ah":
            outcomes = project_ah_home(grid)
        elif market == "ou_2_5":
            outcomes = project_ou25(grid)
        elif market == "btts":
            outcomes = project_btts(grid)
        else:
            return ({"market_outcomes": {}}, 0.0)

        return (
            {"market_outcomes": outcomes, "score_grid": grid},
            confidence,
        )
