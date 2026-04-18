"""
Negelir — Feature engineering pipeline.
Per roadmap §5.2: raw data → ML features with noise injection.
Generates synthetic features for PoC; real pipeline follows same schema.
"""

import random
import numpy as np
import pandas as pd
# FEATURE_COLUMNS lives in constants.py as the single source of truth;
# N_FEATURES is derived from len(FEATURE_COLUMNS).
from common.constants import N_FEATURES, FEATURE_COLUMNS
from common.logger import get_logger

log = get_logger("model.features")


def generate_synthetic_dataset(n_matches: int = 500, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """
    Generate synthetic match features + labels for PoC training.
    Labels: 0 = home win, 1 = draw, 2 = away win (3-class).
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
        elif "yellows" in col or "cards" in col:
            data[col] = rng.uniform(1, 5, size=n_matches)
        elif "fouls" in col:
            data[col] = rng.uniform(8, 18, size=n_matches)
        elif "ht_scored" in col or "ht_conceded" in col:
            data[col] = rng.uniform(0, 1.5, size=n_matches)
        elif "sh_scor" in col or "sh_conced" in col:
            data[col] = rng.uniform(0.3, 1.2, size=n_matches)
        elif "venue_win" in col or "venue_ppg" in col:
            data[col] = rng.uniform(0.2, 0.8, size=n_matches)
        elif "bayesian" in col:
            data[col] = rng.uniform(0.15, 0.40, size=n_matches)
        elif "likelihood" in col:
            data[col] = rng.uniform(0.1, 0.5, size=n_matches)
        elif "sos" in col:
            data[col] = rng.normal(1500, 100, size=n_matches)
        elif "card_factor" in col:
            data[col] = rng.uniform(0, 2, size=n_matches)
        elif col.startswith("qid_"):
            # Query intent distribution features: Dirichlet-like fractions ∈ [0, 1]
            data[col] = rng.uniform(0, 0.5, size=n_matches)
        else:
            data[col] = rng.uniform(0, 3, size=n_matches)

    X = pd.DataFrame(data)

    # 3-class labels: Home(0) / Draw(1) / Away(2)
    # Weighted by elo_diff + form_diff + home advantage + draw tendency
    logit_home = (
        0.3 * (X["home_elo"] - X["away_elo"]) / 400
        + 0.2 * X["form_diff"]
        + 0.15 * X["home_win_ratio_5"]
        - 0.1 * X["away_win_ratio_5"]
        + 0.1  # home advantage
        + rng.normal(0, 0.3, size=n_matches)
    )
    prob_home = 1 / (1 + np.exp(-logit_home))

    # Draw probability from Bayesian draw features + team balance
    elo_balance = 1.0 - np.abs(X["home_elo"] - X["away_elo"]) / 600
    form_balance = 1.0 - np.abs(X["form_diff"])
    draw_base = 0.5 * (X["home_draws_bayesian"] + X["away_draws_bayesian"])
    prob_draw = np.clip(0.15 + 0.15 * elo_balance + 0.10 * form_balance + 0.10 * draw_base
                        + rng.normal(0, 0.08, size=n_matches), 0.08, 0.45)

    # Normalize to proper 3-class probabilities
    prob_away = np.clip(1.0 - prob_home - prob_draw, 0.05, 0.60)
    total = prob_home + prob_draw + prob_away
    prob_home /= total
    prob_draw /= total
    prob_away /= total

    # Sample labels from probabilities
    y_vals = []
    for i in range(n_matches):
        y_vals.append(rng.choice([0, 1, 2], p=[prob_home[i], prob_draw[i], prob_away[i]]))
    y = pd.Series(y_vals, name="result_class")

    dist = y.value_counts(normalize=True).sort_index()
    log.info(f"📊 Dataset: {n_matches} matches, {N_FEATURES} features, "
             f"H={dist.get(0, 0):.2f} D={dist.get(1, 0):.2f} A={dist.get(2, 0):.2f}")
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
