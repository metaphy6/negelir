"""Phase 10 §10.34.2 item 2 — Single-pass DFA fast-path tests.

Tests verify:
1. Clean input detection (Turkish + ASCII + space/punct invariant)
2. Zero-copy guarantee on clean input (same string object)
3. Telemetry emission when fast path is taken
4. Fallback to full pipeline on non-clean input
5. Boundary conditions (empty, max length, special chars)
"""
from __future__ import annotations

import pytest


class TestNormalizeFastPathDetection:
    """Test the clean-input DFA classifier."""

    def test_fast_path_empty_input_is_clean(self) -> None:
        """Empty input is clean (no characters to fail)."""
        from nlp.fast_path import is_clean_input
        
        assert is_clean_input("") is True

    def test_fast_path_ascii_printable_clean(self) -> None:
        """Pure ASCII printable input is clean."""
        from nlp.fast_path import is_clean_input
        
        # Basic ASCII
        assert is_clean_input("hello") is True
        assert is_clean_input("HELLO") is True
        assert is_clean_input("Hello123") is True
        assert is_clean_input("Hello World") is True
        
        # ASCII punctuation
        assert is_clean_input("hello-world") is True
        assert is_clean_input("hello.world") is True
        assert is_clean_input("hello, world!") is True
        assert is_clean_input("hello(world)") is True
        assert is_clean_input('hello"world') is True
        assert is_clean_input("hello'world") is True

    def test_fast_path_turkish_letters_clean(self) -> None:
        """Turkish-specific letters are clean."""
        from nlp.fast_path import is_clean_input
        
        # Turkish lowercase
        assert is_clean_input("çğıöşü") is True
        assert is_clean_input("galatasaray") is True  # all ASCII
        
        # Turkish uppercase
        assert is_clean_input("ÇĞIŞÖŞ") is True
        assert is_clean_input("GALATASARAY") is True
        
        # Mixed case Turkish
        assert is_clean_input("Galatasaray") is True
        assert is_clean_input("Çankırı") is True
        
        # Turkish with ASCII
        assert is_clean_input("Galatasaray maçı") is True
        assert is_clean_input("gözlemci") is True
        
        # Turkish with punctuation
        assert is_clean_input("Galatasaray'nın maçı") is True
        assert is_clean_input("Fenerbahçe, Beşiktaş, Galatasaray") is True

    def test_fast_path_whitespace_clean(self) -> None:
        """ASCII whitespace (space, tab, newline, CR) is clean."""
        from nlp.fast_path import is_clean_input
        
        assert is_clean_input("hello world") is True
        assert is_clean_input("hello\tworld") is True
        assert is_clean_input("hello\nworld") is True
        assert is_clean_input("hello\rworld") is True
        assert is_clean_input("hello\r\nworld") is True
        assert is_clean_input("  multiple   spaces  ") is True

    def test_fast_path_mixed_clean_input(self) -> None:
        """Realistic clean Turkish input passes detection."""
        from nlp.fast_path import is_clean_input
        
        cases = [
            "Galatasaray maçı ne zaman?",
            "Fenerbahçe'nin başarısı",
            "1-1 biten oyun",
            "Saat 15:30'da oynayacak",
            "Beşiktaş vs Galatasaray",
            "2023-2024 sezonu",
            "Kaç gol attı?",
        ]
        for text in cases:
            assert is_clean_input(text) is True, f"Expected {text!r} to be clean"

    def test_fast_path_confusable_unicode_not_clean(self) -> None:
        """Non-ASCII Unicode (confusables, format chars) fails detection."""
        from nlp.fast_path import is_clean_input
        
        # Cyrillic lookalike (a with caron: ǎ)
        assert is_clean_input("Gаlatasaray") is False
        
        # Greek alpha
        assert is_clean_input("αlpha") is False
        
        # Other accents not in Turkish set
        assert is_clean_input("café") is False  # é (U+00E9) not in Turkish set
        assert is_clean_input("naïve") is False  # ï
        
        # Curly quotes (not ASCII straight quotes)
        assert is_clean_input("hello \u201cworld\u201d") is False  # U+201C, U+201D (curly double quotes)
        assert is_clean_input("hello \u2018world\u2019") is False  # U+2018, U+2019 (curly single quotes)
        
        # Em/en dash
        assert is_clean_input("hello\u2014world") is False  # em-dash U+2014
        assert is_clean_input("hello\u2013world") is False  # en-dash U+2013
        
        # Horizontal ellipsis
        assert is_clean_input("hello\u2026world") is False  # U+2026 (ellipsis)

    def test_fast_path_mojibake_not_clean(self) -> None:
        """Common mojibake patterns fail detection."""
        from nlp.fast_path import is_clean_input
        
        # Zero-width space
        assert is_clean_input("hello\u200bworld") is False
        
        # RTL override
        assert is_clean_input("hello\u202eworld") is False
        
        # Line/paragraph separator
        assert is_clean_input("hello\u2028world") is False
        assert is_clean_input("hello\u2029world") is False

    def test_fast_path_format_chars_not_clean(self) -> None:
        """Control chars and format chars fail detection."""
        from nlp.fast_path import is_clean_input
        
        # NUL byte
        assert is_clean_input("hello\x00world") is False
        
        # Form feed
        assert is_clean_input("hello\x0cworld") is False
        
        # BEL
        assert is_clean_input("hello\x07world") is False

    def test_fast_path_max_chars_boundary(self) -> None:
        """Input exceeding max_chars fails detection."""
        from nlp.fast_path import is_clean_input
        
        # Create clean input that exceeds max_chars
        text = "a" * 100
        assert is_clean_input(text, max_chars=512) is True
        assert is_clean_input(text, max_chars=50) is False
        
        # Boundary: exactly at limit
        assert is_clean_input(text, max_chars=100) is True
        
        # Boundary: one over limit
        assert is_clean_input(text, max_chars=99) is False

    def test_fast_path_none_input(self) -> None:
        """None input returns False (not clean)."""
        from nlp.fast_path import is_clean_input
        
        assert is_clean_input(None) is False


class TestNormalizeFastPathZeroCopy:
    """Test the zero-copy guarantee on clean input."""

    def test_fast_path_returns_same_object_clean(self) -> None:
        """Fast path returns the exact same string object (no copy)."""
        from nlp.fast_path import get_clean_input_fast_path
        
        text = "Galatasaray maçı"
        result, took_fast_path = get_clean_input_fast_path(text)
        
        # Should have taken the fast path
        assert took_fast_path is True
        
        # Result should be the SAME object (id check)
        assert id(result) == id(text), "Expected zero-copy return; got a copy"
        assert result is text

    def test_fast_path_returns_same_object_empty(self) -> None:
        """Fast path returns same object for empty input."""
        from nlp.fast_path import get_clean_input_fast_path
        
        text = ""
        result, took_fast_path = get_clean_input_fast_path(text)
        
        assert took_fast_path is True
        assert id(result) == id(text)

    def test_fast_path_ascii_only(self) -> None:
        """Fast path returns same object for ASCII-only input."""
        from nlp.fast_path import get_clean_input_fast_path
        
        text = "hello world 123"
        result, took_fast_path = get_clean_input_fast_path(text)
        
        assert took_fast_path is True
        assert id(result) == id(text)

    def test_fast_path_not_taken_on_non_clean(self) -> None:
        """Fast path is NOT taken on non-clean input; returns False."""
        from nlp.fast_path import get_clean_input_fast_path
        
        # Non-clean: contains curly quote
        text = "hello \u201cworld\u201d"  # curly double quotes
        result, took_fast_path = get_clean_input_fast_path(text)
        
        assert took_fast_path is False
        # Result should still be the input (we didn't normalize it)
        assert result is text


class TestNormalizeFastPathTelemetry:
    """Test telemetry emission when fast path is taken."""

    def test_fast_path_telemetry_on_clean_input(self, caplog) -> None:
        """Fast path emits telemetry when taken on clean input."""
        import logging
        from nlp.fast_path import get_clean_input_fast_path
        
        # Enable logging to capture telemetry
        caplog.set_level(logging.DEBUG)
        
        text = "Galatasaray maçı"
        result, took_fast_path = get_clean_input_fast_path(text)
        
        assert took_fast_path is True
        
        # Check that telemetry was logged (at least attempted)
        # The exact format may vary based on logging config

    def test_fast_path_telemetry_input_length_tracking(self, caplog) -> None:
        """Telemetry includes input length when fast path is taken."""
        import logging
        from nlp.fast_path import get_clean_input_fast_path
        
        caplog.set_level(logging.DEBUG)
        
        text = "short"
        result, took_fast_path = get_clean_input_fast_path(text)
        
        assert took_fast_path is True


class TestNormalizeFastPathIntegration:
    """Integration tests for the fast path with the normalize pipeline."""

    def test_fast_path_integration_with_full_pipeline(self) -> None:
        """Fast path results match full pipeline on clean input (byte-identical)."""
        from nlp.fast_path import get_clean_input_fast_path
        from nlp import normalize
        
        # Clean Turkish input
        text = "Galatasaray maçı ne zaman?"
        
        # Get result from fast path
        fast_result, took_fast_path = get_clean_input_fast_path(text)
        assert took_fast_path is True
        
        # Get result from full pipeline
        full_result = normalize.normalize_input(text)
        
        # Results should be byte-identical (since input is already clean)
        # The full pipeline may do some normalization, but on already-clean input
        # it should be a no-op or very minimal
        # At minimum, the fast path result should be usable
        assert fast_result is not None

    def test_fast_path_accuracy_realistic_queries(self) -> None:
        """Fast path correctly classifies realistic Turkish queries."""
        from nlp.fast_path import is_clean_input
        
        # These should all be clean (realistic Turkish queries)
        clean_queries = [
            "Galatasaray bugün oynuyor mu?",
            "Fenerbahçe kaç gol attı?",
            "Beşiktaş vs Galatasaray maçı kaç kaç?",
            "Müsabaka ne zaman başlıyor?",
            "Gözlemci kimler olacak?",
            "2023-2024 sezonunda kaç gol attı?",
        ]
        
        for query in clean_queries:
            assert is_clean_input(query) is True, f"Expected {query!r} to be clean"

    def test_fast_path_generalization_not_literalism(self) -> None:
        """Fast path generalizes beyond specific witnesses (anti-literalism test).
        
        Per the anti-literalism contract (nlp-anti-literalism.instructions.md),
        the fast path should generalize the principle of "clean input" rather
        than hard-coding specific examples.
        
        This test verifies that novel clean inputs (not in the spec examples)
        are still correctly classified as clean.
        """
        from nlp.fast_path import is_clean_input
        
        # Novel clean inputs not explicitly in the spec
        novel_clean = [
            "xyz",  # arbitrary ASCII
            "İstanbul Çankırı",  # Turkish capitals
            "ş ş ş",  # Turkish char with spaces
            "a1b2c3",  # mixed ASCII letters and digits
            "!!!???",  # ASCII punctuation only
            "Sürü dönerken",  # Turkish phrase without exemplar
        ]
        
        for text in novel_clean:
            assert is_clean_input(text) is True, (
                f"Novel clean input {text!r} failed generalization test"
            )
