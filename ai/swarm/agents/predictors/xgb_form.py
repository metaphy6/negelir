"""`pred.xgb_form.v1` — recent-form predictor.

Phase 5 ships the *agent surface* for an XGBoost-backed predictor.
Until the trainer (Phase 5.4) populates a real booster, the agent
runs a deterministic logistic scoring function over recent-form
features so the swarm has a third independent voter from day one.
The model file path is exposed via :pyattr:`MODEL_PATH` for the
trainer to write into; if a booster is loaded via
:py:meth:`load_booster`, predictions route through it instead.

Features (all default to neutral 0.0 if absent):
  * ``home_form_5`` — points-per-game over last 5 (0.0 .. 3.0)
  * ``away_form_5`` — points-per-game over last 5 (0.0 .. 3.0)
  * ``home_gd_5`` — goal differential over last 5
  * ``away_gd_5`` — goal differential over last 5
  * ``home_advantage`` (default 0.5) — soft prior
"""
from __future__ import annotations

import math
from typing import Any

from ._base import PredictorAgent, PredictorContext, softmax


class XgbFormPredictor(PredictorAgent):
    predictor_id = "pred.xgb_form.v1"
    features_version = "form.v1"

    # Linear coefficients for the H/D/A logits. Hand-tuned floor —
    # the trainer overwrites these once a real booster ships.
    _W_HOME = (0.55, 0.20, 0.40)   # form, gd, ha
    _W_AWAY = (-0.55, -0.20, -0.40)
    _W_DRAW_BIAS = -0.30

    def __init__(self, *, clock: Any = None, booster: Any = None) -> None:
        super().__init__(clock=clock)
        self._booster = booster

    def load_booster(self, booster: Any) -> None:
        """Hot-swap the underlying model (e.g. a trained xgb.Booster)."""
        self._booster = booster

    def _score(self, ctx: PredictorContext) -> dict[str, float]:
        f = ctx.features
        home_form = float(f.get("home_form_5", 1.5))
        away_form = float(f.get("away_form_5", 1.5))
        home_gd = float(f.get("home_gd_5", 0.0))
        away_gd = float(f.get("away_gd_5", 0.0))
        ha = float(f.get("home_advantage", 0.5))

        wh_form, wh_gd, wh_ha = self._W_HOME
        wa_form, wa_gd, wa_ha = self._W_AWAY
        score_h = wh_form * home_form + wh_gd * home_gd + wh_ha * ha
        score_a = wa_form * away_form + wa_gd * away_gd + wa_ha * ha
        # Draw is the residual — stronger when the two sides are even.
        score_d = self._W_DRAW_BIAS - 0.5 * abs(score_h - score_a)
        return {"H": score_h, "D": score_d, "A": score_a}

    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        if self._booster is not None and hasattr(self._booster, "predict"):
            # Real XGBoost path. The booster must accept a 1-row
            # numpy array shaped to features_version. Trainer owns
            # the schema; predictor just routes the call.
            try:
                import numpy as np

                vec = np.asarray(
                    [list(ctx.features.values())], dtype=np.float32
                )
                raw = self._booster.predict(vec)
                p_h, p_d, p_a = (float(x) for x in raw[0][:3])
                z = p_h + p_d + p_a
                if z > 0.0:
                    p_h, p_d, p_a = p_h / z, p_d / z, p_a / z
                pmf_1x2 = {"H": p_h, "D": p_d, "A": p_a}
            except Exception:  # noqa: BLE001
                pmf_1x2 = softmax(self._score(ctx))
        else:
            pmf_1x2 = softmax(self._score(ctx))

        # Confidence: max-class probability minus uniform baseline.
        max_p = max(pmf_1x2.values())
        confidence = max(0.0, min(1.0, (max_p - 1.0 / 3.0) / (2.0 / 3.0)))

        market = ctx.request.market
        if market == "1x2":
            outcomes = pmf_1x2
        elif market == "ah":
            outcomes = {"home": pmf_1x2["H"], "away": pmf_1x2["D"] + pmf_1x2["A"]}
        elif market == "ou_2_5":
            # Project from the H/A asymmetry: lopsided games tend to
            # have more goals (the favorite wins big).
            tilt = abs(pmf_1x2["H"] - pmf_1x2["A"])
            over = 0.50 + 0.25 * tilt
            over = max(0.05, min(0.95, over))
            outcomes = {"over": over, "under": 1.0 - over}
        elif market == "btts":
            # Even matches → btts more likely.
            evenness = 1.0 - abs(pmf_1x2["H"] - pmf_1x2["A"])
            yes = 0.45 + 0.20 * evenness
            yes = max(0.05, min(0.95, yes))
            outcomes = {"yes": yes, "no": 1.0 - yes}
        else:
            return ({"market_outcomes": {}}, 0.0)

        return ({"market_outcomes": outcomes, "score_grid": None}, confidence)
