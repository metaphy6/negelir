"""`pred.dixon_coles.v1` — bivariate Poisson with low-score correction.

Computes a score grid up to ``MAX_GOALS`` using two independent
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
_DEFAULT_RHO = -0.10
# Confidence proxy: how concentrated the score grid is. We use the
# probability mass on the modal cell; higher mass ⇒ more decisive.
_CONFIDENCE_MODAL_FLOOR = 0.05


class DixonColesPredictor(PredictorAgent):
    predictor_id = "pred.dixon_coles.v1"

    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        f = ctx.features
        lam_h = max(0.05, float(f.get("home_xg", _DEFAULT_HOME_XG)))
        lam_a = max(0.05, float(f.get("away_xg", _DEFAULT_AWAY_XG)))
        rho = float(f.get("dixon_coles_rho", _DEFAULT_RHO))

        grid = score_grid(lam_h, lam_a, dc_rho=rho)
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
