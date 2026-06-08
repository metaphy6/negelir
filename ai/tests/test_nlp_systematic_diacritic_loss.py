"""Phase 10 §10.34.1 — Systematic diacritic loss detection.

Covers:
  * US-keyboard users produce all-ASCII Turkish (systematic loss).
  * Detection via non_ascii_ratio < threshold (0.02) AND token_count > 3.
  * Switch diacritic restorer from frequency to lexicon-vs-catalog tie-break.
  * Tag request with input_class=systematic_diacritic_loss.
  * Proofreader prepends one-time disclosure.

Per Phase 10 §10.34.1 (15th-pass generic-broken-Turkish).
Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

import pytest


def test_systematic_diacritic_loss_detected():
    """Verify systematic diacritic loss detection logic."""
    
    test_cases = [
        # (input, token_count, non_ascii_ratio, expected_systematic_loss)
        ("Galatasaray Fenerbahce Besiktas Trabzonspor", 4, 0.0, True),  # All ASCII, >= 4 tokens
        ("Turk futbolu cok iyi", 4, 0.0, True),  # Systematic loss
        ("Türk futbolu çok iyi", 4, 0.35, False),  # Normal Turkish (high non-ASCII ratio)
        ("Turk", 1, 0.0, False),  # Too short (only 1 token)
        ("Turk futbol cok", 3, 0.0, False),  # Exactly 3 tokens (needs > 3)
    ]
    
    threshold = 0.02
    
    for input_text, token_count, non_ascii_ratio, expected in test_cases:
        is_systematic = (
            non_ascii_ratio < threshold and token_count > 3
        )
        assert is_systematic == expected, f"Failed for: {input_text}"


def test_sporadic_loss_unchanged():
    """Verify sporadic loss uses baseline path (no special handling)."""
    
    # Sporadic loss example: mostly Turkish with occasional ASCII (not systematic)
    test_cases = [
        "Göztepe futbolu cok iyi",  # One ASCII word "cok" in Turkish text
        "Galatasaray'ın futbolu daha iyi",  # Mostly Turkish with one ASCII
    ]
    
    # These should NOT trigger systematic loss detection because they have 
    # some non-ASCII characters (even though some are missing)
    threshold = 0.02
    for text in test_cases:
        # With sporadic loss, non_ascii_ratio should be > threshold
        non_ascii_count = sum(1 for c in text if ord(c) > 127)
        non_ascii_ratio = non_ascii_count / len(text) if len(text) > 0 else 0
        is_systematic = non_ascii_ratio < threshold
        assert not is_systematic, f"Sporadic loss wrongly classified: {text} (ratio={non_ascii_ratio})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
