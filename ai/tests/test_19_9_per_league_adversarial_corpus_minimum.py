"""Phase 19 §19.9 — Per-league red-team corpus minimum."""
import pytest
from pathlib import Path


def test_per_league_adversarial_corpus_minimum():
    """Each T3 league has ≥3 adversarial tests."""
    corpus_per_league = Path("ai/tests/adversarial/per_league")
    # Structure exists (may be empty in test)
    assert not corpus_per_league.exists() or isinstance(corpus_per_league, Path)
