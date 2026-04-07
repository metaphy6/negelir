"""
Negelir — GBDT model trainer.
Per roadmap §5.1 & §5.5: XGBoost training with GPU/CPU auto-detect.
Includes feature importance analysis and zero-importance pruning.
"""

import os
import pickle

import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, log_loss

from common.config import cfg
from common.constants import MODEL_VERSION
from common.logger import get_logger, section_banner, success_banner
from model.device import detect_device, get_xgb_params
from model.features import generate_synthetic_dataset, inject_noise, FEATURE_COLUMNS

log = get_logger("model.trainer")


def train_model(save_path: str | None = None) -> xgb.XGBClassifier:
    """
    Train the GBDT base model.
    Uses synthetic data for PoC; real training uses historical match features.
    """
    section_banner("GBDT Model Training")

    device = detect_device()
    params = get_xgb_params(device)

    # Generate training data
    X, y = generate_synthetic_dataset(n_matches=1000, seed=42)
    X = inject_noise(X, noise_pct=0.005, seed=42)

    # Sample weights: upweight draws (class 1) for balance
    sample_weights = y.map({0: 1.0, 1: 2.0, 2: 1.0}).values

    X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
        X, y, sample_weights, test_size=0.2, random_state=42, stratify=y
    )
    log.info(f"📚 Training set: {len(X_train)}, Test set: {len(X_test)}")

    # Train XGBoost (3-class)
    model = xgb.XGBClassifier(**params)
    log.info("🔄 Model training starting...")

    model.fit(
        X_train, y_train,
        sample_weight=w_train,
        eval_set=[(X_test, y_test)],
        sample_weight_eval_set=[w_test],
        verbose=False,
    )

    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    loss = log_loss(y_test, y_prob)

    log.info(f"📈 Test accuracy: {acc:.4f}")
    log.info(f"📉 Test log-loss: {loss:.4f}")

    # Save model
    if save_path is None:
        model_dir = cfg.model_dir
        save_path = os.path.join(model_dir, f"negelir_gbdt_v{MODEL_VERSION}.pkl")

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    with open(save_path, "wb") as f:
        pickle.dump(model, f)
    log.info(f"💾 Model saved: {save_path}")

    # Model size (roadmap: must be < 8 MB)
    size_mb = os.path.getsize(save_path) / (1024 * 1024)
    log.info(f"📦 Model size: {size_mb:.2f} MB")
    if size_mb > 8.0:
        raise ValueError(f"Model size {size_mb:.2f} MB exceeds 8 MB limit")

    # Feature importance (top 10)
    importance = model.feature_importances_
    from model.features import FEATURE_COLUMNS
    top_features = sorted(
        zip(FEATURE_COLUMNS, importance),
        key=lambda x: x[1], reverse=True
    )[:10]
    log.info("🏆 Top 10 features:")
    for feat, imp in top_features:
        log.info(f"   {feat}: {imp:.4f}")

    # Feature importance analysis: identify zero/near-zero importance
    zero_features = [col for col, imp in zip(FEATURE_COLUMNS, importance) if imp < 1e-6]
    low_features = [col for col, imp in zip(FEATURE_COLUMNS, importance)
                    if 1e-6 <= imp < 0.001]
    if zero_features:
        log.info(f"⚠️  Zero-importance features ({len(zero_features)}): "
                 f"{', '.join(zero_features[:5])}{'...' if len(zero_features) > 5 else ''}")
    if low_features:
        log.info(f"📉 Low-importance features ({len(low_features)}): "
                 f"{', '.join(low_features[:5])}{'...' if len(low_features) > 5 else ''}")
    log.info(f"📊 Feature utilization: {len(FEATURE_COLUMNS) - len(zero_features)}/{len(FEATURE_COLUMNS)} "
             f"({100*(1-len(zero_features)/len(FEATURE_COLUMNS)):.0f}%)")

    success_banner(f"Model training complete (v{MODEL_VERSION})")
    return model


def incremental_retrain(model_path: str, new_X: np.ndarray, new_y: np.ndarray,
                        n_rounds: int = 10) -> xgb.XGBClassifier:
    """
    Phase 6: Continue training from saved model, appending new trees.
    Faster than full retrain; maintains learned patterns.

    Args:
        model_path: path to existing .pkl model
        new_X: new feature matrix
        new_y: new labels (0/1/2)
        n_rounds: number of additional boosting rounds

    Returns:
        Updated XGBClassifier
    """
    log.info(f"Incremental retrain: {len(new_y)} new samples, {n_rounds} rounds")

    with open(model_path, "rb") as f:
        model = pickle.load(f)

    # Fit additional rounds on new data
    model.n_estimators = model.n_estimators + n_rounds
    model.fit(
        new_X, new_y,
        xgb_model=model.get_booster(),
        verbose=False,
    )

    # Save updated model
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    log.info(f"Incremental retrain complete → {model_path}")

    return model


if __name__ == "__main__":
    train_model()
