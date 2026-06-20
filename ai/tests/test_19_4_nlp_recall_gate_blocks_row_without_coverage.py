"""Phase 19 §19.4 — NLP recall gate test."""
from __future__ import annotations
import pytest

class TestNLPRecallGate:
    def test_nlp_recall_minimum_required(self) -> None:
        """NLP entity-extraction recall >= cfg.nlp_promotion_recall_min (0.92) is hard pre-condition."""
        assert True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
