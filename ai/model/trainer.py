"""
Negelir — GBDT model trainer.
Per roadmap §5.1 & §5.5: XGBoost training with GPU/CPU auto-detect.
Includes feature importance analysis and zero-importance pruning.
"""

import os
import pickle

import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss

from common.config import cfg
from common.constants import MODEL_VERSION
from common.league_config import get_league_config
from common.logger import get_logger, section_banner, success_banner
from model.device import detect_device, get_xgb_params
from model.features import inject_noise, FEATURE_COLUMNS

log = get_logger("model.trainer")


def train_model(save_path: str | None = None,
                matches: list[dict] | None = None) -> xgb.XGBClassifier:
    """
    Train the GBDT base model on real scraped data.
    Fails loudly if real data is unavailable — no fallback path in production.

    Args:
        save_path: optional path to save model; defaults to cfg.model_dir
        matches: optional pre-loaded match list (used by Phase 3 pipeline to
                 inject the post-holdout split). When None, loads via
                 `load_real_matches()`.
    """
    section_banner("GBDT Model Training")

    device = detect_device()
    league_config = get_league_config(cfg.default_league_id)
    params = get_xgb_params(
        device,
        league_config=league_config,
        random_seed=cfg.training_random_seed,
    )

    from model.real_features import load_real_matches, extract_real_dataset, _parse_date

    league_id = cfg.default_league_id
    min_required = cfg.training_min_matches
    raw_matches = matches if matches is not None else load_real_matches()
    raw_count = len(raw_matches)

    if raw_count == 0:
        raise RuntimeError(
            f"No real matches found for league '{league_id}'. "
            f"Run `make bootstrap LEAGUE={league_id}` first "
            f"(or `make scrape --league {league_id}`)."
        )

    # ── Chronological ordering (Pre-Phase-6 audit P1) ────────────
    # The downstream `train_test_split` was random, which combined
    # with rolling-window features causes temporal leakage: a "test"
    # match's prior matches end up in "train", and "train" matches
    # later in the season carry rolling stats that encode the test
    # match's outcome. Sorting by date here + using a sequential
    # tail slice below gives an honest, time-respecting evaluation.
    # `.get("date", "")` keeps tests that stub raw_matches without
    # dates working — sort becomes a stable no-op in that case.
    raw_matches = sorted(
        raw_matches,
        key=lambda m: _parse_date(m["date"]) if m.get("date") else None,
    ) if all(m.get("date") for m in raw_matches) else list(raw_matches)

    try:
        X, y = extract_real_dataset(min_history=5, matches=raw_matches)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to build training dataset for league '{league_id}' "
            f"from {raw_count} raw matches: {exc}. "
            f"Run `make bootstrap LEAGUE={league_id}` first."
        ) from exc

    if len(X) < min_required:
        raise RuntimeError(
            f"Insufficient training data for league '{league_id}': "
            f"usable={len(X)}, required>={min_required}, raw={raw_count}. "
            "Collect more real history before training. "
            f"Run `make bootstrap LEAGUE={league_id}` first."
        )

    log.info(
        f"🏟️  Training on REAL data: {len(X)} usable matches "
        f"(raw={raw_count}, required>={min_required})"
    )

    X = inject_noise(X, noise_pct=cfg.training_noise_pct, seed=cfg.training_random_seed)

    # Sample weights: upweight draws (class 1) for balance
    sample_weights = y.map(
        lambda cls: cfg.training_sample_weights.get(int(cls), 1.0)
    ).values

    # ── Time-based split ──────────────────────────────────────────
    # `extract_real_dataset` walks chronologically-sorted matches and
    # only emits a row once both teams have `min_history` priors —
    # which means rows themselves are chronological. A sequential
    # tail slice therefore gives a strict "predict later from earlier"
    # evaluation. We deliberately do NOT stratify or shuffle.
    test_split = float(cfg.training_test_split)
    if not 0.0 < test_split < 1.0:
        raise ValueError(
            f"training_test_split must be in (0,1); got {test_split!r}"
        )
    n_total = len(X)
    n_test = max(1, int(round(n_total * test_split)))
    split_at = n_total - n_test
    X_train = X.iloc[:split_at].reset_index(drop=True)
    X_test = X.iloc[split_at:].reset_index(drop=True)
    y_train = y.iloc[:split_at].reset_index(drop=True)
    y_test = y.iloc[split_at:].reset_index(drop=True)
    w_train = sample_weights[:split_at]
    w_test = sample_weights[split_at:]
    log.info(
        f"📚 Training set: {len(X_train)}, Test set: {len(X_test)} "
        f"(time-based split; first {len(X_train)} rows train, "
        f"last {len(X_test)} test)"
    )

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
    if size_mb > cfg.model_max_size_mb:
        raise ValueError(
            f"Model size {size_mb:.2f} MB exceeds {cfg.model_max_size_mb:.2f} MB limit"
        )

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
