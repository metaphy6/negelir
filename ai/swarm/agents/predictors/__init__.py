"""Phase 5 predictor swarm.

Each predictor is an `Agent` (subscribes to `predict.request`,
publishes `predict.vote`). The package layout mirrors ROADMAP §5.1:
one module per backend, all inheriting from `PredictorAgent` in
``_base.py``. The Phase R2 directory move (`swarm/predictors/`) is
a `git mv` away — the import surface (`swarm.agents.predictors.*`)
already matches the steady-state shape.
"""
from __future__ import annotations

from ._base import (
    CalibrationStore,
    InMemoryCalibrationStore,
    PredictorAgent,
    PredictorContext,
    softmax,
)
from .dixon_coles import DixonColesPredictor
from .elo import EloPredictor
from .lgbm_market import LgbmMarketPredictor
from .xgb_form import XgbFormPredictor
from .xgb_xg import XgbXgPredictor

__all__ = [
    "CalibrationStore",
    "DixonColesPredictor",
    "EloPredictor",
    "InMemoryCalibrationStore",
    "LgbmMarketPredictor",
    "PredictorAgent",
    "PredictorContext",
    "XgbFormPredictor",
    "XgbXgPredictor",
    "softmax",
]
