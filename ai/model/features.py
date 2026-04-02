"""
Negelir — Feature engineering pipeline.
Per roadmap §5.2: raw data → ML features with noise injection.
Generates synthetic features for PoC; real pipeline follows same schema.
"""

import random
import numpy as np
import pandas as pd
from common.constants import N_FEATURES, CURRENT_SEASON
from common.logger import get_logger

log = get_logger("model.features")

# Feature column names (91 features per roadmap §5.4)
FEATURE_COLUMNS = [
    # Team form (rolling windows)
    "home_avg_scored_3", "home_avg_scored_5", "home_avg_scored_10",
    "home_avg_conceded_3", "home_avg_conceded_5", "home_avg_conceded_10",
    "home_ppg_5", "home_ppg_10", "home_clean_sheet_10",
    "home_win_ratio_5", "home_draw_ratio_5", "home_loss_ratio_5",
    "away_avg_scored_3", "away_avg_scored_5", "away_avg_scored_10",
    "away_avg_conceded_3", "away_avg_conceded_5", "away_avg_conceded_10",
    "away_ppg_5", "away_ppg_10", "away_clean_sheet_10",
    "away_win_ratio_5", "away_draw_ratio_5", "away_loss_ratio_5",
    # Elo & derived
    "home_elo", "away_elo", "elo_diff",
    "home_xg", "away_xg", "xg_diff",
    "home_form_index", "away_form_index", "form_diff",
    # H2H
    "h2h_home_win_pct", "h2h_draw_pct", "h2h_avg_goals",
    "h2h_over25_pct", "h2h_bts_pct", "h2h_count",
    # League position
    "home_league_pos_norm", "away_league_pos_norm", "pos_diff",
    "home_goal_diff", "away_goal_diff",
    "home_pts_gap_leader", "away_pts_gap_leader",
    "home_pts_gap_relegation", "away_pts_gap_relegation",
    # Squad & tactical
    "home_formation_stability", "away_formation_stability",
    "home_squad_rotation_gini", "away_squad_rotation_gini",
    "home_goal_concentration", "away_goal_concentration",
    "home_avg_age", "away_avg_age",
    # Contextual
    "home_fixture_congestion_7d", "away_fixture_congestion_7d",
    "home_fixture_congestion_14d", "away_fixture_congestion_14d",
    "home_manager_tenure", "away_manager_tenure",
    "home_manager_change", "away_manager_change",
    "derby_flag", "season_phase",
    "match_week_norm",
    # Temporal
    "day_sin", "day_cos", "month_sin", "month_cos",
    "home_rest_days", "away_rest_days", "rest_diff",
    # Sentiment
    "home_media_sentiment", "away_media_sentiment",
    "home_fan_optimism", "away_fan_optimism",
    "media_consensus_strength",
    # Derived
    "style_matchup_index", "fatigue_diff",
    "home_momentum", "away_momentum",
    "home_scoring_consistency", "away_scoring_consistency",
    "surprise_index_home", "surprise_index_away",
    # Weather / venue
    "temperature_bucket", "precipitation_flag", "wind_category",
    "venue_type",
]

assert len(FEATURE_COLUMNS) == N_FEATURES, f"Expected {N_FEATURES} features, got {len(FEATURE_COLUMNS)}"


def generate_synthetic_dataset(n_matches: int = 500, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """
    Generate synthetic match features + labels for PoC training.
    Labels: 0 = away/draw, 1 = home win (simplified binary).
    """
    log.info(f"🏭 Generating synthetic data: {n_matches} matches...")
    rng = np.random.RandomState(seed)

    data = {}
    for col in FEATURE_COLUMNS:
        if "flag" in col or "change" in col:
            data[col] = rng.randint(0, 2, size=n_matches).astype(float)
        elif "ratio" in col or "pct" in col or "norm" in col or "index" in col:
            data[col] = rng.uniform(0, 1, size=n_matches)
        elif "elo" in col:
            data[col] = rng.normal(1500, 200, size=n_matches)
        elif "age" in col:
            data[col] = rng.normal(26, 3, size=n_matches)
        elif "sentiment" in col or "optimism" in col:
            data[col] = rng.uniform(-1, 1, size=n_matches)
        elif "sin" in col or "cos" in col:
            data[col] = rng.uniform(-1, 1, size=n_matches)
        elif "week" in col or "tenure" in col or "rest" in col:
            data[col] = rng.randint(1, 35, size=n_matches).astype(float)
        elif "congestion" in col:
            data[col] = rng.randint(0, 5, size=n_matches).astype(float)
        elif "bucket" in col or "category" in col or "type" in col or "phase" in col:
            data[col] = rng.randint(0, 4, size=n_matches).astype(float)
        else:
            data[col] = rng.uniform(0, 3, size=n_matches)

    X = pd.DataFrame(data)

    # Synthetic labels: weighted by elo_diff + form_diff + home advantage
    logit = (
        0.3 * (X["home_elo"] - X["away_elo"]) / 400
        + 0.2 * X["form_diff"]
        + 0.15 * X["home_win_ratio_5"]
        - 0.1 * X["away_win_ratio_5"]
        + 0.1  # home advantage
        + rng.normal(0, 0.3, size=n_matches)
    )
    prob = 1 / (1 + np.exp(-logit))
    y = (prob > 0.5).astype(int)
    y = pd.Series(y, name="home_win")

    log.info(f"📊 Dataset: {n_matches} matches, {N_FEATURES} features, home win rate: {y.mean():.2f}")
    return X, y


def inject_noise(features: pd.DataFrame, noise_pct: float = 0.005, seed: int | None = None) -> pd.DataFrame:
    """
    Per roadmap §6.2 Stage 5: inject ±0.5% uniform noise to prevent back-calculation.
    """
    rng = np.random.RandomState(seed)
    noise = rng.uniform(1 - noise_pct, 1 + noise_pct, size=features.shape)
    noised = features * noise
    return noised


def extract_features_for_match(match_data: dict) -> np.ndarray:
    """
    Convert a match data dict (from Go server or DB) to a feature vector.
    Returns a 1×91 numpy array ready for model inference.
    """
    vec = np.zeros(N_FEATURES, dtype=np.float32)

    # Map available data to feature slots
    col_to_idx = {col: i for i, col in enumerate(FEATURE_COLUMNS)}

    for key, idx in col_to_idx.items():
        if key in match_data:
            val = match_data[key]
            if val is not None:
                vec[idx] = float(val)

    return vec.reshape(1, -1)
