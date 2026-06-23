"""Negelir — Backtesting and prediction accuracy evaluation.

Pivot v3 component: backtest (moved from ai/backtest/ in Phase 22.4).

Evaluates model prediction accuracy against historical data,
computes betting performance metrics, and reports
model quality and ROI.

Public API: backtesting, evaluation, metrics computation.
"""

__all__ = [
    "CompetitionBacktest",
    "BetTypeEvaluator",
    "AccuracyEvaluator",
]
