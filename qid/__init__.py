"""Negelir — Query Intent Distribution (QID).

Pivot v3 component: qid (moved from ai/qid/ in Phase 22.4).

Phase 10 (Turkish NLP) component: collects and aggregates user query intent
distributions and converts them into predictive features for the ML model.

Public API: intent collection, aggregation, feature derivation.
"""

__all__ = [
    "QueryIntentCollector",
    "IntentAggregator",
    "qid_features_from_intent_dist",
]
