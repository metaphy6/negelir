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

from ai.common.config import cfg
from ai.common.constants import MODEL_VERSION, N_FEATURES
from ai.common.league_config import LeagueConfig, get_league_config
from ai.common.logger import get_logger
from model.features import FEATURE_COLUMNS

log = get_logger("model.inference")

# Feature range validation (roadmap §5.6.2). Defaults live in `cfg.feature_ranges`
# and are overridable via NEGELIR_FEATURE_RANGES_JSON. The module-level alias
# is kept for back-compat with callers that imported `FEATURE_RANGES` directly.
FEATURE_RANGES = cfg.feature_ranges

def _dixon_coles_tau(hg, ag, home_xg, away_xg, rho: float):
    """Dixon-Coles correction factor for low-scoring matches."""
    if hg == 0 and ag == 0:
        return 1.0 - home_xg * away_xg * rho
    elif hg == 1 and ag == 0:
        return 1.0 + away_xg * rho
    elif hg == 0 and ag == 1:
        return 1.0 + home_xg * rho
    elif hg == 1 and ag == 1:
        return 1.0 - rho
    return 1.0


def _score_prob(hg, ag, home_xg, away_xg, rho: float):
    """Score probability with Dixon-Coles correction."""
    p = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)
    p *= _dixon_coles_tau(hg, ag, home_xg, away_xg, rho=rho)
    return max(0.0, float(p))


def _score_matrix(home_xg: float, away_xg: float, home_cap: int,
                  away_cap: int, rho: float, normalise: bool = False) -> np.ndarray:
    """
    Vectorised (home_cap+1) × (away_cap+1) Dixon–Coles score-probability matrix.
    Replaces the historical nested-loop computation; results are numerically
    identical (up to fp rounding).
    """
    h_pmf = poisson.pmf(np.arange(home_cap + 1), home_xg)
    a_pmf = poisson.pmf(np.arange(away_cap + 1), away_xg)
    m = np.outer(h_pmf, a_pmf)

    # Apply Dixon–Coles low-score corrections in the 2×2 sub-matrix
    if home_cap >= 1 and away_cap >= 1:
        m[0, 0] *= 1.0 - home_xg * away_xg * rho
        m[1, 0] *= 1.0 + away_xg * rho
        m[0, 1] *= 1.0 + home_xg * rho
        m[1, 1] *= 1.0 - rho

    np.maximum(m, 0.0, out=m)

    if normalise:
        total = m.sum()
        if total > 0:
            m = m / total
    return m


class ModelShim:
    """Backward-compatibility shim for 120-feature models in a 147-feature environment."""
    
    def __init__(self, model: xgb.XGBClassifier, feature_schema_version: int = 1):
        self.model = model
        self.feature_schema_version = feature_schema_version
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict with feature slicing if needed."""
        if self.feature_schema_version == 1:
            # Old 120-col model: slice features to first 120 columns
            X_sliced = X[:, :120]
            return self.model.predict(X_sliced)
        else:
            return self.model.predict(X)
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities with feature slicing if needed."""
        if self.feature_schema_version == 1:
            X_sliced = X[:, :120]
            return self.model.predict_proba(X_sliced)
        else:
            return self.model.predict_proba(X)


class GBDTInference:
    def __init__(self, model_path: str | None = None, league_config: LeagueConfig | None = None):
        self.league_config = league_config or get_league_config()

        if model_path is None:
            model_path = os.path.join(cfg.model_dir, f"negelir_gbdt_v{MODEL_VERSION}.pkl")

        self.model: ModelShim | None = None
        self.model_path = model_path
        self.feature_schema_version = 1
        self.model_feature_count = 120
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.model_path):
            with open(self.model_path, "rb") as f:
                loaded = pickle.load(f)
            
            # Handle both old (direct model) and new (metadata dict) formats
            if isinstance(loaded, dict) and "model" in loaded:
                inner_model = loaded["model"]
                self.feature_schema_version = loaded.get("feature_schema_version", 1)
                self.model_feature_count = loaded.get("n_features", 120)
                self.model = ModelShim(inner_model, feature_schema_version=self.feature_schema_version)
                log.info(f"📦 Model loaded: {self.model_path}")
                log.info(f"🏷️  Feature schema version: {self.feature_schema_version}")
            else:
                # Backward-compat: old model format (direct XGBClassifier)
                self.model = ModelShim(loaded, feature_schema_version=1)
                self.feature_schema_version = 1
                self.model_feature_count = 120
                log.info(f"📦 Model loaded: {self.model_path} (legacy format, schema v1)")
        else:
            log.warning(f"⚠️  Model not found: {self.model_path}")
            log.info("🔄 Training new model from real data...")
            from model.trainer import train_model
            trained_model = train_model(self.model_path)
            self.model = ModelShim(trained_model, feature_schema_version=2)
            self.feature_schema_version = 2
            self.model_feature_count = 147

    def validate_features(self, features: np.ndarray) -> tuple[bool, str]:
        """
        Per roadmap §5.6.2: validate feature vector schema and ranges.
        """
        if features.shape != (1, N_FEATURES):
            return False, f"Feature vector shape error: {features.shape}, expected: (1, {N_FEATURES})"

        if np.any(np.isnan(features)) or np.any(np.isinf(features)):
            return False, "NaN or Inf value detected"

        # Range validation per feature type
        feature_ranges = cfg.feature_ranges
        for i, col in enumerate(FEATURE_COLUMNS):
            val = features[0, i]
            for key, (lo, hi) in feature_ranges.items():
                if key in col:
                    if val < lo or val > hi:
                        features[0, i] = np.clip(val, lo, hi)
                    break

        return True, ""

    def _adjust_xg_with_elo(self, home_xg: float, away_xg: float,
                             home_elo: float, away_elo: float) -> tuple[float, float]:
        """
        Adjust xG using Elo differential and league home advantage.
        Elo difference maps to a multiplicative factor via logistic curve.
        """
        elo_diff = home_elo - away_elo + self.league_config.elo_home_advantage
        # Logistic mapping: elo_diff → multiplier in ~[min, min+range]
        # 400 Elo diff ≈ 10:1 expected, but we dampen for xG adjustment
        factor = 1.0 / (1.0 + 10.0 ** (-elo_diff / self.league_config.elo_xg_divisor))
        # factor is in [0,1]; map to multiplier centered around 1.0
        f_min = self.league_config.xg_elo_factor_min
        f_range = self.league_config.xg_elo_factor_range
        home_mult = f_min + factor * f_range
        away_mult = (f_min + f_range) - factor * f_range

        adj_home = max(self.league_config.min_xg_floor, home_xg * home_mult)
        adj_away = max(self.league_config.min_xg_floor, away_xg * away_mult)
        return adj_home, adj_away

    def _venue_adjusted_xg(self, features: np.ndarray, col_idx: dict,
                            home_xg: float, away_xg: float) -> tuple[float, float]:
        """
        Weight xG by home/away form — teams that score more at home/away
        get a venue-specific boost.
        """
        home_scored_home = float(features[0, col_idx.get("home_avg_scored_home_5", 0)])
        away_scored_away = float(features[0, col_idx.get("away_avg_scored_away_5", 0)])
        home_scored_all = float(features[0, col_idx.get("home_avg_scored_5", 0)])
        away_scored_all = float(features[0, col_idx.get("away_avg_scored_5", 0)])

        # Venue ratio: how much better/worse a team scores at home/away
        v_floor = self.league_config.venue_ratio_floor
        v_ceil = self.league_config.venue_ratio_ceiling
        if home_scored_all > 0.1 and home_scored_home > 0.01:
            home_venue_ratio = min(v_ceil, max(v_floor, home_scored_home / home_scored_all))
        else:
            home_venue_ratio = 1.0
        if away_scored_all > 0.1 and away_scored_away > 0.01:
            away_venue_ratio = min(v_ceil, max(v_floor, away_scored_away / away_scored_all))
        else:
            away_venue_ratio = 1.0

        return home_xg * home_venue_ratio, away_xg * away_venue_ratio

    def _poisson_home_win_prob(self, home_xg: float, away_xg: float) -> float:
        rho = self.league_config.dixon_coles_rho
        home_cap = self.league_config.poisson_home_goal_cap
        away_cap = self.league_config.poisson_away_goal_cap
        m = _score_matrix(home_xg, away_xg, home_cap, away_cap, rho)
        return float(np.tril(m, k=-1).sum())

    def _poisson_draw_prob(self, home_xg: float, away_xg: float) -> float:
        rho = self.league_config.dixon_coles_rho
        cap = self.league_config.poisson_draw_goal_cap
        m = _score_matrix(home_xg, away_xg, cap, cap, rho)
        return float(np.trace(m))

    def _predict_scorelines(self, home_xg: float, away_xg: float, top_n: int = 5) -> list[dict]:
        rho = self.league_config.dixon_coles_rho
        home_cap = self.league_config.poisson_home_goal_cap
        away_cap = self.league_config.poisson_away_goal_cap
        m = _score_matrix(home_xg, away_xg, home_cap, away_cap, rho)
        scorelines = [
            {"home": h, "away": a, "probability": round(float(m[h, a]), 4)}
            for h in range(home_cap + 1)
            for a in range(away_cap + 1)
        ]
        scorelines.sort(key=lambda x: -x["probability"])
        return scorelines[:top_n]

    def _compute_score_brackets(self, home_xg: float, away_xg: float) -> dict:
        """Compute probability brackets for score ranges."""
        rho = self.league_config.dixon_coles_rho
        home_cap = self.league_config.poisson_home_goal_cap
        away_cap = self.league_config.poisson_away_goal_cap
        m = _score_matrix(home_xg, away_xg, home_cap, away_cap, rho, normalise=True)

        # Total goals per cell (broadcast row + col indices)
        h_idx = np.arange(home_cap + 1)[:, None]
        a_idx = np.arange(away_cap + 1)[None, :]
        totals = h_idx + a_idx

        p_0 = float(m[0, 0])
        p_1 = float(m[totals == 1].sum())
        p_2 = float(m[totals == 2].sum())
        p_3 = float(m[totals == 3].sum())
        p_4plus = float(m[totals >= 4].sum())

        # Most likely total goals
        max_total = int(totals.max())
        per_total = np.bincount(totals.ravel(), weights=m.ravel(), minlength=max_total + 1)
        most_likely_total = int(per_total.argmax())

        return {
            "goals_0": round(p_0, 3),
            "goals_1": round(p_1, 3),
            "goals_2": round(p_2, 3),
            "goals_3": round(p_3, 3),
            "goals_4_plus": round(p_4plus, 3),
            "most_likely_total_goals": most_likely_total,
        }

    def _compute_betting_markets(self, home_xg: float, away_xg: float) -> dict:
        rho = self.league_config.dixon_coles_rho
        max_g = self.league_config.poisson_market_goal_cap
        m = _score_matrix(home_xg, away_xg, max_g, max_g, rho, normalise=True)

        h_idx = np.arange(max_g + 1)[:, None]
        a_idx = np.arange(max_g + 1)[None, :]
        totals = h_idx + a_idx
        diff = h_idx - a_idx

        def p_over(line: int) -> float:
            return float(m[totals > line].sum())

        p_home = float(m[diff > 0].sum())
        p_draw = float(np.trace(m))
        p_away = max(0.01, 1.0 - p_home - p_draw)

        p_h_zero = float(m[0, :].sum())
        p_a_zero = float(m[:, 0].sum())
        p_btts = 1.0 - p_h_zero - p_a_zero + float(m[0, 0])

        # Half-time (first-half goal percentage from league config)
        ht_pct = self.league_config.first_half_goal_pct
        ht_hxg = home_xg * ht_pct
        ht_axg = away_xg * ht_pct
        ht_cap = self.league_config.poisson_ht_max_goals
        # Half-time uses raw Poisson (no Dixon–Coles correction in original code)
        ht_h_pmf = poisson.pmf(np.arange(ht_cap + 1), ht_hxg)
        ht_a_pmf = poisson.pmf(np.arange(ht_cap + 1), ht_axg)
        ht_m = np.outer(ht_h_pmf, ht_a_pmf)
        ht_h_idx = np.arange(ht_cap + 1)[:, None]
        ht_a_idx = np.arange(ht_cap + 1)[None, :]
        ht_diff = ht_h_idx - ht_a_idx
        ht_home = float(ht_m[ht_diff > 0].sum())
        ht_draw = float(np.trace(ht_m))
        ht_away = max(0.01, 1.0 - ht_home - ht_draw)

        ah_h_m15 = float(m[diff >= 2].sum())
        denom_ha = max(0.01, p_home + p_away)

        return {
            "over_1_5": round(p_over(1), 3),
            "over_2_5": round(p_over(2), 3),
            "over_3_5": round(p_over(3), 3),
            "btts": round(float(p_btts), 3),
            "dc_1x": round(p_home + p_draw, 3),
            "dc_x2": round(p_draw + p_away, 3),
            "dc_12": round(p_home + p_away, 3),
            "dnb_home": round(p_home / denom_ha, 3),
            "dnb_away": round(p_away / denom_ha, 3),
            "ah_home_m1_5": round(ah_h_m15, 3),
            "ht_home": round(ht_home, 3),
            "ht_draw": round(ht_draw, 3),
            "ht_away": round(ht_away, 3),
            "ht_over_0_5": round(float(1.0 - ht_m[0, 0]), 3),
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
            features: 1×N_FEATURES numpy array

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
        xg_floor = self.league_config.min_xg_floor
        home_avg_goals = max(xg_floor, float(features[0, col_idx["home_avg_scored_5"]]))
        away_avg_goals = max(xg_floor, float(features[0, col_idx["away_avg_scored_5"]]))
        home_xg_feat = float(features[0, col_idx["home_xg"]])
        away_xg_feat = float(features[0, col_idx["away_xg"]])

        # Use xG if available, else fall back to average goals
        home_xg = home_xg_feat if home_xg_feat > 0.1 else home_avg_goals
        away_xg = away_xg_feat if away_xg_feat > 0.1 else away_avg_goals

        # Elo-adjusted xG — modulate lambdas by Elo differential
        home_elo = float(features[0, col_idx.get("home_elo", 0)])
        away_elo = float(features[0, col_idx.get("away_elo", 0)])
        if home_elo > 100 and away_elo > 100:
            home_xg, away_xg = self._adjust_xg_with_elo(home_xg, away_xg, home_elo, away_elo)

        # Venue-adjusted xG — weight by home/away specific scoring rates
        home_xg, away_xg = self._venue_adjusted_xg(features, col_idx, home_xg, away_xg)

        p_home_poisson = self._poisson_home_win_prob(home_xg, away_xg)
        p_draw_poisson = self._poisson_draw_prob(home_xg, away_xg)
        p_away_poisson = max(0.01, 1.0 - p_home_poisson - p_draw_poisson)

        # --- Ensemble blend (weight from league config) ---
        xgb_w = self.league_config.xgb_weight
        pw = 1.0 - xgb_w
        home_win_prob = xgb_w * xgb_home + pw * p_home_poisson
        draw_prob = xgb_w * xgb_draw + pw * p_draw_poisson
        away_win_prob = xgb_w * xgb_away + pw * p_away_poisson

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

        # --- Score prediction (Poisson) with bracket analysis ---
        top_scorelines = self._predict_scorelines(home_xg, away_xg, top_n=5)
        score_brackets = self._compute_score_brackets(home_xg, away_xg)

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
            "score_brackets": score_brackets,
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
