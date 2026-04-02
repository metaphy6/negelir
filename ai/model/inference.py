"""
Negelir — GBDT model inference.
Per roadmap §5.4: produces analysis JSON from feature vectors.
Includes input validation per roadmap §5.6.2 Feature Vector Firewall.
"""

import os
import pickle
import time

import numpy as np
import xgboost as xgb

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
    "default": (-100, 100),
}


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

    def predict(self, features: np.ndarray) -> dict:
        """
        Run inference and return analysis JSON (per roadmap §5.4).

        Args:
            features: 1×91 numpy array

        Returns:
            Analysis dict with probabilities, confidence, feature importance
        """
        # Validate
        is_valid, error = self.validate_features(features)
        if not is_valid:
            log.error(f"⛔ Feature validation error: {error}")
            return self._low_confidence_result(error)

        # Inference with timing (roadmap: <300ms)
        t0 = time.perf_counter()
        proba = self.model.predict_proba(features)[0]
        home_win_prob = float(proba[1]) if len(proba) > 1 else float(proba[0])
        away_win_prob = 1.0 - home_win_prob
        draw_prob = min(0.3, 1.0 - abs(home_win_prob - away_win_prob))  # heuristic

        # Normalize distribution
        total = home_win_prob + away_win_prob + draw_prob
        home_win_prob /= total
        away_win_prob /= total
        draw_prob /= total

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

        # Goal metrics (derived from features)
        home_avg_goals = float(features[0, FEATURE_COLUMNS.index("home_avg_scored_5")])
        away_avg_goals = float(features[0, FEATURE_COLUMNS.index("away_avg_scored_5")])
        total_goals_est = home_avg_goals + away_avg_goals
        over25_prob = float(min(0.95, max(0.05, 1.0 / (1.0 + np.exp(-(total_goals_est - 2.5))))))
        bts_prob = float(min(0.95, max(0.05, home_avg_goals * away_avg_goals / 4.0)))

        analysis = {
            "model_version": MODEL_VERSION,
            "confidence": round(confidence, 3),
            "distribution": {
                "home_win": round(home_win_prob, 3),
                "draw": round(draw_prob, 3),
                "away_win": round(away_win_prob, 3),
            },
            "goal_metrics": {
                "expected_total_goals": round(total_goals_est, 2),
                "over_2_5_prob": round(over25_prob, 3),
                "bts_prob": round(bts_prob, 3),
            },
            "feature_importance": feature_importance,
            "features_used": N_FEATURES,
        }

        log.info(
            f"🧠 Prediction: H={analysis['distribution']['home_win']:.2f} "
            f"D={analysis['distribution']['draw']:.2f} "
            f"A={analysis['distribution']['away_win']:.2f} "
            f"(confidence: {analysis['confidence']:.2f})"
        )
        return analysis

    def _low_confidence_result(self, reason: str) -> dict:
        return {
            "model_version": MODEL_VERSION,
            "confidence": 0.1,
            "distribution": {"home_win": 0.33, "draw": 0.34, "away_win": 0.33},
            "goal_metrics": {"expected_total_goals": 2.5, "over_2_5_prob": 0.5, "bts_prob": 0.5},
            "feature_importance": {},
            "features_used": 0,
            "error": reason,
        }
