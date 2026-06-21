"""
Negelir — Feature engineering pipeline.
Per roadmap §5.2: raw data -> ML features with noise injection.
Contains runtime-safe feature helpers only.
"""

import numpy as np
import pandas as pd

# FEATURE_COLUMNS lives in constants.py as the single source of truth;
# N_FEATURES is derived from len(FEATURE_COLUMNS).
from ai.common.constants import FEATURE_COLUMNS, N_FEATURES


def inject_noise(features: pd.DataFrame, noise_pct: float = 0.005, seed: int | None = None) -> pd.DataFrame:
    """
    Per roadmap §6.2 Stage 5: inject +-noise_pct uniform noise.
    """
    rng = np.random.RandomState(seed)
    noise = rng.uniform(1 - noise_pct, 1 + noise_pct, size=features.shape)
    noised = features * noise
    return noised


def extract_features_for_match(match_data: dict) -> np.ndarray:
    """
    Convert a match data dict (from Go server or DB) to a feature vector.
    Returns a 1 x N_FEATURES numpy array ready for model inference.
    """
    vec = np.zeros(N_FEATURES, dtype=np.float32)

    # Map available data to feature slots.
    col_to_idx = {col: i for i, col in enumerate(FEATURE_COLUMNS)}

    for key, idx in col_to_idx.items():
        if key in match_data:
            val = match_data[key]
            if val is not None:
                vec[idx] = float(val)

    return vec.reshape(1, -1)
