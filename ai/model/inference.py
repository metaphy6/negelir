"""
Negelir — GBDT model inference (v0.2).
3-class (Home/Draw/Away) + Poisson ensemble + score/card prediction.
Per roadmap §5.4: produces analysis JSON from feature vectors.
Includes input validation per roadmap §5.6.2 Feature Vector Firewall.
"""

import os
import pickle
import time

import numpy as np
import xgboost as xgb
from scipy.stats import poisson

from common.config import cfg
from common.constants import MODEL_VERSION, N_FEATURES
from common.logger import get_logger
from model.features import FEATURE_COLUMNS

log = get_logger("model.inference")

# Feature range validation (roadmap §5.6.2)
FEATURE_RANGES = {
    "elo": (-500, 3500),
    "ratio": (0, 1),
    "pct": (0, 100),
    "norm": (0, 1),
    "sentiment": (-1, 1),
    "optimism": (-1, 1),
    "sin": (-1, 1),
    "cos": (-1, 1),
    "flag": (0, 1),
    "age": (15, 45),
    "scored": (0, 10),
    "conceded": (0, 10),
    "yellows": (0, 10),
    "fouls": (0, 40),
    "cards": (0, 15),
    "bayesian": (0, 1),
    "sos": (800, 2200),
    "default": (-100, 100),
}

# Ensemble weight: XGBoost vs Poisson
XGB_WEIGHT = 0.55


class GBDTInference:
    def __init__(self, model_path: str | None = None):
        if model_path is None:
            model_path = os.path.join(cfg.model_dir, f"negelir_gbdt_v{MODEL_VERSION}.pkl")

        self.model: xgb.XGBClassifier | None = None
        self.model_path = model_path
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.model_path):
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(f)
            log.info(f"📦 Model loaded: {self.model_path}")
        else:
            log.warning(f"⚠️  Model not found: {self.model_path}")
            log.info("🔄 Training new model...")
            from model.trainer import train_model
            self.model = train_model(self.model_path)

    def validate_features(self, features: np.ndarray) -> tuple[bool, str]:
        """
        Per roadmap §5.6.2: validate feature vector schema and ranges.
        """
        if features.shape != (1, N_FEATURES):
            return False, f"Feature vector shape error: {features.shape}, expected: (1, {N_FEATURES})"

        if np.any(np.isnan(features)) or np.any(np.isinf(features)):
            return False, "NaN or Inf value detected"

        # Range validation per feature type
        for i, col in enumerate(FEATURE_COLUMNS):
            val = features[0, i]
            for key, (lo, hi) in FEATURE_RANGES.items():
                if key in col:
                    if val < lo or val > hi:
                        features[0, i] = np.clip(val, lo, hi)
                    break

        return True, ""

    def _poisson_home_win_prob(self, home_xg: float, away_xg: float) -> float:
        p = 0.0
        for h in range(8):
            for a in range(h):
                p += poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg)
        return p

    def _poisson_draw_prob(self, home_xg: float, away_xg: float) -> float:
        p = 0.0
        for k in range(6):
            p += poisson.pmf(k, home_xg) * poisson.pmf(k, away_xg)
        return p

    def _predict_scorelines(self, home_xg: float, away_xg: float, top_n: int = 5) -> list[dict]:
        scorelines = []
        for h in range(8):
            for a in range(8):
                p = float(poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg))
                scorelines.append({"home": h, "away": a, "probability": round(p, 4)})
        scorelines.sort(key=lambda x: -x["probability"])
        return scorelines[:top_n]

    def _compute_betting_markets(self, home_xg: float, away_xg: float) -> dict:
        max_g = 7
        sm = {}
        for h in range(max_g):
            for a in range(max_g):
                sm[(h, a)] = poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg)

        def p_over(line):
            return 1.0 - sum(sm[(h, a)] for h in range(max_g) for a in range(max_g) if h + a <= line)

        p_home = sum(sm[(h, a)] for h in range(max_g) for a in range(h))
        p_draw = sum(sm[(k, k)] for k in range(max_g))
        p_away = max(0.01, 1.0 - p_home - p_draw)

        p_h_zero = sum(sm[(0, a)] for a in range(max_g))
        p_a_zero = sum(sm[(h, 0)] for h in range(max_g))
        p_btts = 1.0 - p_h_zero - p_a_zero + sm[(0, 0)]

        # Half-time (47% of goals in first half — Turkish league empirical)
        ht_hxg = home_xg * 0.47
        ht_axg = away_xg * 0.47
        ht_sm = {}
        for h in range(5):
            for a in range(5):
                ht_sm[(h, a)] = poisson.pmf(h, ht_hxg) * poisson.pmf(a, ht_axg)
        ht_home = sum(ht_sm[(h, a)] for h in range(5) for a in range(h))
        ht_draw = sum(ht_sm[(k, k)] for k in range(5))
        ht_away = max(0.01, 1.0 - ht_home - ht_draw)

        ah_h_m15 = sum(sm[(h, a)] for h in range(max_g) for a in range(max_g) if h - a >= 2)
        denom_ha = max(0.01, p_home + p_away)

        return {
            "over_1_5": round(float(p_over(1)), 3),
            "over_2_5": round(float(p_over(2)), 3),
            "over_3_5": round(float(p_over(3)), 3),
            "btts": round(float(p_btts), 3),
            "dc_1x": round(float(p_home + p_draw), 3),
            "dc_x2": round(float(p_draw + p_away), 3),
            "dc_12": round(float(p_home + p_away), 3),
            "dnb_home": round(float(p_home / denom_ha), 3),
            "dnb_away": round(float(p_away / denom_ha), 3),
            "ah_home_m1_5": round(float(ah_h_m15), 3),
            "ht_home": round(float(ht_home), 3),
            "ht_draw": round(float(ht_draw), 3),
            "ht_away": round(float(ht_away), 3),
            "ht_over_0_5": round(float(1.0 - ht_sm[(0, 0)]), 3),
        }

    def _estimate_cards(self, features: np.ndarray, derby: bool) -> dict:
        """Estimate card counts from foul/discipline features."""
        col_idx = {col: i for i, col in enumerate(FEATURE_COLUMNS)}

        home_fouls = float(features[0, col_idx.get("home_avg_fouls_5", 0)])
        away_fouls = float(features[0, col_idx.get("away_avg_fouls_5", 0)])
        home_yellows_hist = float(features[0, col_idx.get("home_avg_yellows_5", 0)])
        away_yellows_hist = float(features[0, col_idx.get("away_avg_yellows_5", 0)])

        # Base expectation from historical card rates
        base_yellows = home_yellows_hist + away_yellows_hist
        if base_yellows < 1.0:
            # Fallback to foul-based estimation
            base_yellows = (home_fouls + away_fouls) / 3.5

        # Derby multiplier
        multiplier = 1.3 if derby else 1.0
        expected_yellows = base_yellows * multiplier

        # Red card probability
        red_prob = 0.15 if derby else 0.08

        return {
            "expected_yellows": round(float(expected_yellows), 1),
            "expected_yellows_home": round(float(expected_yellows * home_fouls / max(0.1, home_fouls + away_fouls)), 1),
            "expected_yellows_away": round(float(expected_yellows * away_fouls / max(0.1, home_fouls + away_fouls)), 1),
            "red_card_probability": round(float(red_prob), 3),
            "over_3_5_cards": round(float(min(0.95, max(0.05, 1.0 / (1.0 + np.exp(-(expected_yellows - 3.5)))))), 3),
            "over_4_5_cards": round(float(min(0.95, max(0.05, 1.0 / (1.0 + np.exp(-(expected_yellows - 4.5)))))), 3),
        }

    def predict(self, features: np.ndarray) -> dict:
        """
        Run inference and return full analysis JSON.
        3-class XGBoost + Poisson ensemble with score/card predictions.

        Args:
            features: 1×120 numpy array

        Returns:
            Analysis dict with probabilities, scores, cards, markets
        """
        # Validate
        is_valid, error = self.validate_features(features)
        if not is_valid:
            log.error(f"⛔ Feature validation error: {error}")
            return self._low_confidence_result(error)

        # Inference with timing (roadmap: <300ms)
        t0 = time.perf_counter()

        # --- XGBoost 3-class probabilities ---
        proba = self.model.predict_proba(features)[0]
        # Handle both binary (legacy pkl) and 3-class models
        if len(proba) == 3:
            xgb_home = float(proba[0])
            xgb_draw = float(proba[1])
            xgb_away = float(proba[2])
        else:
            # Legacy binary model: approximate 3-class
            xgb_home = float(proba[1]) if len(proba) > 1 else float(proba[0])
            xgb_away = 1.0 - xgb_home
            xgb_draw = min(0.30, 1.0 - abs(xgb_home - xgb_away))
            total_xgb = xgb_home + xgb_draw + xgb_away
            xgb_home /= total_xgb
            xgb_draw /= total_xgb
            xgb_away /= total_xgb

        # --- Poisson model probabilities ---
        col_idx = {col: i for i, col in enumerate(FEATURE_COLUMNS)}
        home_avg_goals = max(0.3, float(features[0, col_idx["home_avg_scored_5"]]))
        away_avg_goals = max(0.3, float(features[0, col_idx["away_avg_scored_5"]]))
        home_xg_feat = float(features[0, col_idx["home_xg"]])
        away_xg_feat = float(features[0, col_idx["away_xg"]])

        # Use xG if available, else fall back to average goals
        home_xg = home_xg_feat if home_xg_feat > 0.1 else home_avg_goals
        away_xg = away_xg_feat if away_xg_feat > 0.1 else away_avg_goals

        p_home_poisson = self._poisson_home_win_prob(home_xg, away_xg)
        p_draw_poisson = self._poisson_draw_prob(home_xg, away_xg)
        p_away_poisson = max(0.01, 1.0 - p_home_poisson - p_draw_poisson)

        # --- Ensemble blend ---
        pw = 1.0 - XGB_WEIGHT
        home_win_prob = XGB_WEIGHT * xgb_home + pw * p_home_poisson
        draw_prob = XGB_WEIGHT * xgb_draw + pw * p_draw_poisson
        away_win_prob = XGB_WEIGHT * xgb_away + pw * p_away_poisson

        # Normalize
        total = home_win_prob + draw_prob + away_win_prob
        home_win_prob /= total
        draw_prob /= total
        away_win_prob /= total

        inference_ms = (time.perf_counter() - t0) * 1000
        if inference_ms > 300:
            log.warning(f"⚠️  Inference time {inference_ms:.1f}ms exceeds 300ms limit")
        else:
            log.debug(f"⏱  Inference time: {inference_ms:.1f}ms")

        # Confidence from entropy
        probs = np.array([home_win_prob, draw_prob, away_win_prob])
        entropy = -np.sum(probs * np.log(probs + 1e-10))
        max_entropy = np.log(3)
        confidence = float(1.0 - (entropy / max_entropy))
        confidence = np.clip(confidence, 0.1, 0.95)

        # Feature importance
        importances = self.model.feature_importances_
        top_indices = np.argsort(importances)[-5:][::-1]
        feature_importance = {
            FEATURE_COLUMNS[i]: float(importances[i])
            for i in top_indices
        }

        # --- Goal metrics ---
        total_goals_est = home_xg + away_xg
        over25_prob = float(min(0.95, max(0.05, 1.0 / (1.0 + np.exp(-(total_goals_est - 2.5))))))
        bts_prob = float(min(0.95, max(0.05, home_xg * away_xg / 4.0)))

        # --- Score prediction (Poisson) ---
        top_scorelines = self._predict_scorelines(home_xg, away_xg, top_n=5)

        # --- Card prediction ---
        derby = bool(features[0, col_idx["derby_flag"]] > 0.5)
        card_prediction = self._estimate_cards(features, derby)

        # --- Betting markets ---
        betting_markets = self._compute_betting_markets(home_xg, away_xg)

        analysis = {
            "model_version": MODEL_VERSION,
            "confidence": round(float(confidence), 3),
            "distribution": {
                "home_win": round(home_win_prob, 3),
                "draw": round(draw_prob, 3),
                "away_win": round(away_win_prob, 3),
            },
            "goal_metrics": {
                "expected_total_goals": round(total_goals_est, 2),
                "over_2_5_prob": round(over25_prob, 3),
                "bts_prob": round(bts_prob, 3),
                "home_xg": round(home_xg, 2),
                "away_xg": round(away_xg, 2),
            },
            "score_prediction": top_scorelines,
            "card_prediction": card_prediction,
            "betting_markets": betting_markets,
            "feature_importance": feature_importance,
            "features_used": N_FEATURES,
        }

        log.info(
            f"🧠 Prediction: H={analysis['distribution']['home_win']:.2f} "
            f"D={analysis['distribution']['draw']:.2f} "
            f"A={analysis['distribution']['away_win']:.2f} "
            f"(confidence: {analysis['confidence']:.2f}) "
            f"Score: {top_scorelines[0]['home']}-{top_scorelines[0]['away']} "
            f"Cards: ~{card_prediction['expected_yellows']} yellows"
        )
        return analysis

    def _low_confidence_result(self, reason: str) -> dict:
        return {
            "model_version": MODEL_VERSION,
            "confidence": 0.1,
            "distribution": {"home_win": 0.33, "draw": 0.34, "away_win": 0.33},
            "goal_metrics": {"expected_total_goals": 2.5, "over_2_5_prob": 0.5, "bts_prob": 0.5,
                             "home_xg": 1.3, "away_xg": 1.2},
            "score_prediction": [{"home": 1, "away": 1, "probability": 0.12}],
            "card_prediction": {"expected_yellows": 4.0, "expected_yellows_home": 2.0,
                                "expected_yellows_away": 2.0, "red_card_probability": 0.08,
                                "over_3_5_cards": 0.5, "over_4_5_cards": 0.4},
            "betting_markets": {},
            "feature_importance": {},
            "features_used": 0,
            "error": reason,
        }
