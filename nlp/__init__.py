"""Negelir — Turkish NLP layer.

Pivot v3 component: nlp (moved from ai/nlp/ in Phase 22.4).

Phase 10 (Turkish NLP) implements:
- Intent detection (qa.intent.v1)
- Answer generation (qa.answer.v1)
- Normalization and entity extraction

Public API: intent classification, answer rendering, entity normalization.
"""

__all__ = [
    # Intent detection
    "Intent",
    "IntentClassifier",
    # Answer generation  
    "Answer",
    "AnswerRenderer",
    # Normalization
    "normalize_tr",
    # Entity extraction
    "EntityExtractor",
]
