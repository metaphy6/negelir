"""
Negelir — GPU/CPU device detection.
Per requirement #11: target RTX 4080, fallback to CPU dynamically.
"""

import os
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


def get_xgb_params(device: str) -> dict:
    """Return XGBoost parameters appropriate for the detected device."""
    base_params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "min_child_weight": 3,
        "seed": 42,
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
