"""Phase 6 — Proofreader swarm package.

Currently exports:

- `checks.py`     — pure-function rules (range/consistency/plausibility)
- `aggregator.py` — quorum aggregator (ProofreaderAggregatorAgent)

Phase 6.2 will add per-replica `ProofreaderAgent` shells that wrap
``checks.py`` and emit `predict.proofreader_verdict.v1`.

The legacy `ai/proofreader/` package re-exports `checks.RANGES` so
the old pipeline callers see a single source of truth.
"""
from .aggregator import ProofreaderAggregatorAgent
from .checks import RANGES, consistency_check, plausibility_check, range_check
from .prediction_checks import (
    grid_consistency_check,
    plausibility_check as prediction_plausibility_check,
    sanity_check,
)
from .replicas import (
    ConsistencyProofreader,
    PlausibilityProofreader,
    SanityProofreader,
)

__all__ = [
    "ProofreaderAggregatorAgent",
    "RANGES",
    "range_check",
    "consistency_check",
    "plausibility_check",
    "sanity_check",
    "prediction_plausibility_check",
    "grid_consistency_check",
    "SanityProofreader",
    "PlausibilityProofreader",
    "ConsistencyProofreader",
]
