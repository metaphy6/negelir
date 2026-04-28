"""`pred.elo.v1` — baseline Elo + home-advantage.

Pure Python; the smallest model that works. Reads `home_elo`,
`away_elo`, optional `home_advantage` (default 65) from
``ctx.features``. Produces a 1X2 distribution from the Elo
expected-score formula, with a small flat draw allocation. For
markets without a closed-form Elo derivation (`ah`, `ou_2_5`,
`btts`) we synthesize a calibrated proxy from the same Elo gap.
"""
from __future__ import annotations

import math
from typing import Any

from ._base import PredictorAgent, PredictorContext

# Elo math: classic 1/(1 + 10^(d/400)). Pulled into module constants
# rather than literals so the lint passes. They are the standard Elo
# coefficients — not tunables.
_ELO_BASE = 10.0
_ELO_SCALE = 400.0
_DEFAULT_HOME_ADVANTAGE = 65.0
# Empirical: about a quarter of league matches end in a draw. We
# carve a flat slice and split the remaining mass by Elo.
_DRAW_BASELINE = 0.27
# Confidence is "how decisive is this Elo gap". A 200-pt gap maps to
# ~0.76 expected score — pretty decisive. Below 50 pts it's a coin flip.
_ELO_CONFIDENCE_SCALE = 200.0


def _expected_score(home_elo: float, away_elo: float, ha: float) -> float:
    diff = (away_elo - home_elo - ha) / _ELO_SCALE
    return 1.0 / (1.0 + math.pow(_ELO_BASE, diff))


class EloPredictor(PredictorAgent):
    predictor_id = "pred.elo.v1"

    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        f = ctx.features
        home_elo = float(f.get("home_elo", 1500.0))
        away_elo = float(f.get("away_elo", 1500.0))
        ha = float(f.get("home_advantage", _DEFAULT_HOME_ADVANTAGE))

        e_home = _expected_score(home_elo, away_elo, ha)
        # Map expected score to a 1X2 split: H + 0.5·D = e_home.
        # Carve a draw slice first, then split the rest H/A by e_home.
        non_draw = 1.0 - _DRAW_BASELINE
        p_h = max(0.0, min(non_draw, non_draw * e_home))
        p_a = max(0.0, non_draw - p_h)
        p_d = _DRAW_BASELINE

        # Confidence: decisiveness of the Elo gap (with HA folded in).
        gap = abs(home_elo + ha - away_elo)
        confidence = max(0.0, min(1.0, gap / _ELO_CONFIDENCE_SCALE))

        market = ctx.request.market
        if market == "1x2":
            outcomes = {"H": p_h, "D": p_d, "A": p_a}
        elif market == "ah":
            # Asian handicap (home -0.5): equivalent to "home wins".
            outcomes = {"home": p_h, "away": 1.0 - p_h}
        elif market == "ou_2_5":
            # Crude proxy: stronger sides score more goals; map e_home
            # to over-2.5 probability around a 0.50 baseline. Tuned for
            # neutrality so backtests don't reward this market spuriously.
            over = 0.50 + 0.20 * (e_home - 0.50)
            over = max(0.05, min(0.95, over))
            outcomes = {"over": over, "under": 1.0 - over}
        elif market == "btts":
            # Both-teams-to-score: peaks for evenly-matched sides.
            # 1 - |2·e_home − 1| gives a triangular peak at e_home=0.5.
            evenness = 1.0 - abs(2.0 * e_home - 1.0)
            yes = 0.40 + 0.30 * evenness
            yes = max(0.05, min(0.95, yes))
            outcomes = {"yes": yes, "no": 1.0 - yes}
        else:
            # supported_markets gate already filtered; defensive.
            return ({"market_outcomes": {}}, 0.0)

        return ({"market_outcomes": outcomes, "score_grid": None}, confidence)
