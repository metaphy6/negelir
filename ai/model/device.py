"""
Negelir — GPU/CPU device detection.
Per requirement #11: target RTX 4080, fallback to CPU dynamically.
"""

import os

from common.league_config import LeagueConfig, get_league_config
from common.logger import get_logger

log = get_logger("model.device")


def detect_device() -> str:
    """
    Detect the best available compute device.
    Returns 'cuda' if GPU available, 'cpu' otherwise.
    Respects AI_DEVICE env override.
    """
    forced = os.getenv("AI_DEVICE", "auto").lower()
    if forced == "cpu":
        log.info("🖥️  Device: CPU (manual override)")
        return "cpu"
    if forced == "cuda":
        log.info("🎮 Device: CUDA GPU (manual override)")
        return "cuda"

    # Auto-detect: try a real GPU operation
    try:
        import xgboost as xgb
        import numpy as np
        import warnings
        # Attempt a tiny training on GPU — if XGBoost warns, it means no real GPU
        dtrain = xgb.DMatrix(np.zeros((2, 1)), label=[0, 1])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            xgb.train({"tree_method": "hist", "device": "cuda", "verbosity": 0}, dtrain, num_boost_round=1)
            gpu_warnings = [x for x in w if "GPU" in str(x.message) or "gpu" in str(x.message) or "CPU" in str(x.message)]
            if not gpu_warnings:
                log.info("🎮 Device: CUDA GPU (verified)")
                return "cuda"
    except Exception:
        pass

    log.info("🖥️  Device: CPU (GPU not found, falling back to CPU)")
    return "cpu"


def get_xgb_params(
    device: str,
    league_config: LeagueConfig | None = None,
    random_seed: int | None = None,
) -> dict:
    """Return XGBoost parameters appropriate for the detected device."""
    cfg = league_config or get_league_config()
    seed = random_seed if random_seed is not None else 42

    base_params = {
        "objective": "multi:softprob",
        "num_class": 3,
        "eval_metric": "mlogloss",
        "max_depth": cfg.xgb_max_depth,
        "learning_rate": cfg.xgb_learning_rate,
        "n_estimators": cfg.xgb_n_estimators,
        "subsample": cfg.xgb_subsample,
        "colsample_bytree": cfg.xgb_colsample_bytree,
        "reg_alpha": cfg.xgb_reg_alpha,
        "reg_lambda": cfg.xgb_reg_lambda,
        "min_child_weight": cfg.xgb_min_child_weight,
        "gamma": cfg.xgb_gamma,
        "n_jobs": -1,
        "seed": seed,
    }

    if device == "cuda":
        base_params["tree_method"] = "hist"
        base_params["device"] = "cuda"
        log.info("🎮 XGBoost params: GPU (hist + cuda)")
    else:
        base_params["tree_method"] = "hist"
        base_params["device"] = "cpu"
        log.info("🖥️  XGBoost params: CPU (hist)")

    return base_params
