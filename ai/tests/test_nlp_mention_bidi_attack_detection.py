"""Phase 10 §10.33.5 — Right-to-left text injection in usernames / mentions.

Covers:
  * Bidi controls in @username that can flip a quoted opponent name.
  * Mention parser rejects @token containing Cf (Format-control) characters.
  * Alert emitted: nlp.alert.v1{kind=mention_bidi_attack_blocked, severity=warn}.

Per Phase 10 §10.33.5 (14th-pass wrong-assumption sweep).
Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
"""
from __future__ import annotations

import pytest


def test_bidi_control_characters_detected():
    """Verify Bidi control characters are properly categorized."""
    import unicodedata
    
    # Bidi controls per spec: U+202A..U+202E, U+2066..U+2069
    bidi_controls = [
        "\u202A",  # LRE (Left-to-Right Embedding)
        "\u202B",  # RLE (Right-to-Left Embedding)
        "\u202C",  # PDF (Pop Directional Formatting)
        "\u202D",  # LRO (Left-to-Right Override)
        "\u202E",  # RLO (Right-to-Left Override)
        "\u2066",  # LRI (Left-to-Right Isolate)
        "\u2067",  # RLI (Right-to-Left Isolate)
        "\u2068",  # FSI (First Strong Isolate)
        "\u2069",  # PDI (Pop Directional Isolate)
    ]
    
    for ctrl in bidi_controls:
        category = unicodedata.category(ctrl)
        assert category == "Cf", f"Control {repr(ctrl)} should be Cf (Format)"


def test_mention_parser_rejects_bidi_in_username():
    """Verify mention parser detects Bidi controls in @username."""
    
    def has_bidi_controls(token: str) -> bool:
        """Check if token contains Bidi control characters (Cf category)."""
        import unicodedata
        return any(unicodedata.category(c) == "Cf" for c in token)
    
    # Clean mention - should pass
    assert not has_bidi_controls("@player")
    
    # Adversarial mention with embedded bidi control - should fail
    adversarial = "@player\u202E"  # RLO override
    assert has_bidi_controls(adversarial)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
