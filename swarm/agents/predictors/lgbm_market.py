"""`pred.lgbm_market.v1` — opt-in odds-derived predictor.

Behind ``cfg.predictor_market_features_enabled`` (default false) per
ROADMAP §5.1. Requires an odds processor to populate
``match_normalized.record_type='odds'`` rows; until then the agent
just refuses to start.

Like the XGB predictors, Phase 5 ships the agent surface; the trainer
populates a real LightGBM booster later. Until then the agent uses a
deterministic transform of the implied odds (vig-removed) so the
swarm has a market-anchored vote when the flag is enabled.

Features (all optional; first available pair wins):
  * ``odds_home``, ``odds_draw``, ``odds_away`` — decimal odds
  * ``odds_over_2_5``, ``odds_under_2_5``
  * ``odds_btts_yes``, ``odds_btts_no``
"""
from __future__ import annotations

from typing import Any

from ._base import PredictorAgent, PredictorContext


def _devig_two(p1: float, p2: float) -> tuple[float, float]:
    z = p1 + p2
    if z <= 0.0:
        return 0.5, 0.5
    return p1 / z, p2 / z


def _devig_three(p1: float, p2: float, p3: float) -> tuple[float, float, float]:
    z = p1 + p2 + p3
    if z <= 0.0:
        return 1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0
    return p1 / z, p2 / z, p3 / z


class LgbmMarketPredictor(PredictorAgent):
    predictor_id = "pred.lgbm_market.v1"
    features_version = "market.v1"

    def __init__(self, *, clock: Any = None, booster: Any = None) -> None:
        super().__init__(clock=clock)
        self._booster = booster

    def load_booster(self, booster: Any) -> None:
        self._booster = booster

    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        f = ctx.features
        market = ctx.request.market

        if market == "1x2":
            oh = float(f.get("odds_home", 0.0) or 0.0)
            od = float(f.get("odds_draw", 0.0) or 0.0)
            oa = float(f.get("odds_away", 0.0) or 0.0)
            if min(oh, od, oa) <= 1.0:
                return ({"market_outcomes": {}}, 0.0)  # no odds, no vote
            ph, pd, pa = _devig_three(1.0 / oh, 1.0 / od, 1.0 / oa)
            outcomes = {"H": ph, "D": pd, "A": pa}
            modal = max(outcomes.values())
        elif market == "ah":
            oh = float(f.get("odds_home", 0.0) or 0.0)
            oa = float(f.get("odds_away", 0.0) or 0.0)
            if min(oh, oa) <= 1.0:
                return ({"market_outcomes": {}}, 0.0)
            ph, pa = _devig_two(1.0 / oh, 1.0 / oa)
            outcomes = {"home": ph, "away": pa}
            modal = max(outcomes.values())
        elif market == "ou_2_5":
            ov = float(f.get("odds_over_2_5", 0.0) or 0.0)
            un = float(f.get("odds_under_2_5", 0.0) or 0.0)
            if min(ov, un) <= 1.0:
                return ({"market_outcomes": {}}, 0.0)
            po, pu = _devig_two(1.0 / ov, 1.0 / un)
            outcomes = {"over": po, "under": pu}
            modal = max(outcomes.values())
        elif market == "btts":
            yes = float(f.get("odds_btts_yes", 0.0) or 0.0)
            no_ = float(f.get("odds_btts_no", 0.0) or 0.0)
            if min(yes, no_) <= 1.0:
                return ({"market_outcomes": {}}, 0.0)
            py, pn = _devig_two(1.0 / yes, 1.0 / no_)
            outcomes = {"yes": py, "no": pn}
            modal = max(outcomes.values())
        else:
            return ({"market_outcomes": {}}, 0.0)

        confidence = max(0.0, min(1.0, modal))
        return ({"market_outcomes": outcomes, "score_grid": None}, confidence)
