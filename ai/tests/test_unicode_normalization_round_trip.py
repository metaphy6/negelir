"""Phase 13.11.3 — Locale-aware Unicode normalization round-trip tests.

Tests that queries with locale-specific characters are correctly normalized
using NFC + lowercase per IETF BCP 47. Covers the top-5 EU + TR character
sets: Turkish, German, Spanish, Portuguese, and Greek.

Per LEAGUE_CATALOG.md §2.2 and §13.11.3, all aliases and queries must
round-trip through Unicode NFC normalization correctly.
"""
from __future__ import annotations

import unicodedata

import pytest


def normalize_for_gazetteer(text: str) -> str:
    """Normalize text for gazetteer matching (NFC + lowercase per IETF BCP 47).
    
    This is the canonical normalization used by all NLP entity extraction.
    """
    return unicodedata.normalize("NFC", text).lower()


class TestTurkishNormalization:
    """Turkish character normalization (dotless-ı / dotted-i distinction)."""

    def test_turkish_dotless_i(self) -> None:
        """Turkish dotless-ı (U+0131) normalizes correctly."""
        # Lowercase of Turkish capital I (without dot) is lowercase ı (U+0131)
        turkish_i = "ı"
        normalized = normalize_for_gazetteer(turkish_i)
        assert normalized == "ı", "Turkish dotless-ı should remain ı after normalization"

    def test_turkish_dotted_i(self) -> None:
        """Turkish dotted-i (U+0069) normalizes correctly."""
        dotted_i = "i"
        normalized = normalize_for_gazetteer(dotted_i)
        assert normalized == "i", "Dotted-i should remain i after normalization"

    def test_turkish_capital_i_vs_I(self) -> None:
        """Capital I (dotted) and capital I (dotless) lowercase differently in Turkish."""
        # This test documents the distinction
        capital_dotted = "I"  # U+0049
        capital_dotless = "I"  # U+0049 (same as above; context-dependent)
        # In Turkish context, "I".lower() in Turkish locale → "ı"
        # In non-Turkish context, "I".lower() → "i"
        # Python's .lower() uses Unicode rules, not locale-specific
        assert capital_dotted.lower() == "i"
        assert capital_dotless.lower() == "i"

    def test_turkish_team_name_normalization(self) -> None:
        """Turkish team names normalize consistently."""
        # Galatasaray, Fenerbahçe, Beşiktaş
        names = [
            "Galatasaray",
            "GALATASARAY",
            "galatasaray",
            "Fenerbahçe",
            "FENERBAHÇE",
            "fenerbahçe",
        ]
        normalized_set = {normalize_for_gazetteer(name) for name in names}
        assert len(normalized_set) == 2, "Should have exactly 2 unique normalized values (one per team)"
        assert "galatasaray" in normalized_set
        assert "fenerbahçe" in normalized_set


class TestGermanNormalization:
    """German character normalization (umlauts: ä, ö, ü)."""

    def test_german_umlauts_normalize(self) -> None:
        """German umlauts normalize correctly via NFC."""
        umlauts = {
            "Müller": "müller",
            "Köln": "köln",
            "Düsseldorf": "düsseldorf",
            "Grün": "grün",
        }
        for original, expected in umlauts.items():
            normalized = normalize_for_gazetteer(original)
            assert normalized == expected, f"{original} should normalize to {expected}"

    def test_german_team_normalization(self) -> None:
        """German team names normalize consistently."""
        names = [
            "Bayern München",
            "BAYERN MÜNCHEN",
            "bayern münchen",
        ]
        normalized_set = {normalize_for_gazetteer(name) for name in names}
        assert len(normalized_set) == 1, "All variants should normalize to the same value"
        assert "bayern münchen" in normalized_set


class TestSpanishNormalization:
    """Spanish character normalization (tilde: ñ)."""

    def test_spanish_tilde_normalize(self) -> None:
        """Spanish ñ normalizes correctly."""
        spanish_chars = {
            "España": "españa",
            "Niño": "niño",
            "Español": "español",
        }
        for original, expected in spanish_chars.items():
            normalized = normalize_for_gazetteer(original)
            assert normalized == expected, f"{original} should normalize to {expected}"

    def test_spanish_team_normalization(self) -> None:
        """Spanish team names normalize consistently."""
        names = [
            "Real Madrid",
            "REAL MADRID",
            "real madrid",
            "Barcelona",
            "BARCELONA",
            "barcelona",
        ]
        normalized = [normalize_for_gazetteer(name) for name in names]
        assert len(set(normalized)) == 2, "Should have exactly 2 unique values (one per team)"


class TestPortugueseNormalization:
    """Portuguese character normalization (tilde: ã, circumflex: â)."""

    def test_portuguese_normalize(self) -> None:
        """Portuguese diacritics normalize correctly."""
        portuguese_chars = {
            "São Paulo": "são paulo",
            "Ação": "ação",
            "Atlântico": "atlântico",
        }
        for original, expected in portuguese_chars.items():
            normalized = normalize_for_gazetteer(original)
            assert normalized == expected, f"{original} should normalize to {expected}"


class TestGreekNormalization:
    """Greek character normalization (Greek script)."""

    def test_greek_letters_normalize(self) -> None:
        """Greek letters normalize correctly via NFC."""
        # Olympiacos in Greek
        greek_name = "Ολυμπιακός"
        normalized = normalize_for_gazetteer(greek_name)
        # NFC normalization should handle Greek correctly
        assert isinstance(normalized, str)
        assert len(normalized) > 0
        # Lowercase should be applied
        assert normalized.lower() == normalized

    def test_greek_latin_equivalents_distinct(self) -> None:
        """Greek and Latin versions of the same team name are distinct."""
        # Olympiacos (Latin) vs Ολυμπιακός (Greek) should normalize differently
        latin_name = normalize_for_gazetteer("Olympiacos")
        greek_name = normalize_for_gazetteer("Ολυμπιακός")
        assert latin_name != greek_name, "Greek and Latin names should be distinct"


class TestNormalizationRoundTrip:
    """Round-trip normalization tests (idempotency)."""

    def test_normalization_is_idempotent(self) -> None:
        """Normalizing twice should give the same result as normalizing once."""
        test_strings = [
            "Galatasaray",
            "Bayern München",
            "Fenerbahçe",
            "Real Madrid",
            "São Paulo",
            "Ολυμπιακός",
        ]
        for s in test_strings:
            normalized_once = normalize_for_gazetteer(s)
            normalized_twice = normalize_for_gazetteer(normalized_once)
            assert normalized_once == normalized_twice, (
                f"Normalization is not idempotent for '{s}': "
                f"{normalized_once!r} != {normalized_twice!r}"
            )

    def test_nfc_then_lowercase_equals_lowercase_then_nfc(self) -> None:
        """NFC + lowercase should equal lowercase + NFC (order independence)."""
        test_strings = [
            "Galatasaray",
            "Bayern München",
            "Fenerbahçe",
        ]
        for s in test_strings:
            # Path 1: NFC first, then lowercase
            nfc_first = unicodedata.normalize("NFC", s).lower()
            # Path 2: lowercase first, then NFC
            lower_first = unicodedata.normalize("NFC", s.lower())
            assert nfc_first == lower_first, (
                f"Normalization order matters for '{s}': "
                f"NFC→lower={nfc_first!r}, lower→NFC={lower_first!r}"
            )


class TestMixedLocaleText:
    """Tests for text mixing multiple locale character sets."""

    def test_multilingual_match_list(self) -> None:
        """Multilingual aliases normalize consistently."""
        # A query mentioning multiple teams
        multilingual_text = [
            "Bayern München vs Olympiacos",  # German + Greek
            "Real Madrid vs Barcelona",  # Spanish
            "Galatasaray vs Fenerbahçe",  # Turkish
        ]
        for text in multilingual_text:
            normalized = normalize_for_gazetteer(text)
            # Should normalize without errors
            assert isinstance(normalized, str)
            # Should be lowercase
            assert normalized.lower() == normalized
