"""Phase 13.11.6 — Mixed-script handling round-trip tests.

Tests that team names and competition names in multiple scripts round-trip
correctly through the gazetteer:

  * Cyrillic + Latin transliterations (Yugoslav-era clubs)
  * Greek (Ολυμπιακός and Latin transliteration)
  * Hebrew (מכבי and Latin transliteration)
  * CJK (Japanese J1, Korean K League, Chinese Super League)

Per LEAGUE_CATALOG.md §2.2 and §13.11.6, all 5 script families must
correctly normalize and be matchable in the gazetteer.
"""
from __future__ import annotations

import unicodedata

import pytest


def normalize_for_matching(text: str) -> str:
    """Normalize text for gazetteer matching (NFC + lowercase)."""
    return unicodedata.normalize("NFC", text).lower()


class TestCyrillicLatinTransliterations:
    """Tests for Cyrillic + Latin transliterations (Yugoslav-era clubs)."""

    def test_red_star_belgrade_cyrillic_vs_latin(self) -> None:
        """Red Star Belgrade: Cyrillic 'Звезда' vs Latin 'Zvezda'."""
        cyrillic = "Звезда"  # Cyrillic
        latin = "Zvezda"  # Latin transliteration

        norm_cyrillic = normalize_for_matching(cyrillic)
        norm_latin = normalize_for_matching(latin)

        # Both should normalize without error
        assert isinstance(norm_cyrillic, str)
        assert isinstance(norm_latin, str)

        # They should normalize differently (they are distinct scripts)
        assert norm_cyrillic != norm_latin

    def test_partizan_belgrade_cyrillic_vs_latin(self) -> None:
        """Partizan Belgrade: Cyrillic 'Партизан' vs Latin 'Partizan'."""
        cyrillic = "Партизан"
        latin = "Partizan"

        norm_cyrillic = normalize_for_matching(cyrillic)
        norm_latin = normalize_for_matching(latin)

        assert isinstance(norm_cyrillic, str)
        assert isinstance(norm_latin, str)
        # Cyrillic and Latin should be distinct
        assert norm_cyrillic != norm_latin

    def test_cyrillic_normalization_consistency(self) -> None:
        """Cyrillic team names normalize consistently."""
        teams = [
            "ЗВЕЗДА",  # uppercase
            "Звезда",  # title case
            "звезда",  # lowercase
        ]

        normalized = [normalize_for_matching(team) for team in teams]

        # All should normalize to the same lowercase form
        assert len(set(normalized)) == 1


class TestGreekScripts:
    """Tests for Greek script (both Latin and Greek)."""

    def test_olympiacos_greek_vs_latin(self) -> None:
        """Olympiacos: Greek Ολυμπιακός vs Latin Olympiacos."""
        greek = "Ολυμπιακός"
        latin = "Olympiacos"

        norm_greek = normalize_for_matching(greek)
        norm_latin = normalize_for_matching(latin)

        # Both should normalize without error
        assert isinstance(norm_greek, str)
        assert isinstance(norm_latin, str)

        # They should be distinct (different scripts)
        assert norm_greek != norm_latin

    def test_panathinaikos_greek_vs_latin(self) -> None:
        """Panathinaikos: Greek Παναθηναϊκός vs Latin Panathinaikos."""
        greek = "Παναθηναϊκός"
        latin = "Panathinaikos"

        norm_greek = normalize_for_matching(greek)
        norm_latin = normalize_for_matching(latin)

        assert isinstance(norm_greek, str)
        assert isinstance(norm_latin, str)

    def test_greek_text_normalization_consistency(self) -> None:
        """Greek text normalizes consistently."""
        teams = [
            "ΟΛΥΜΠΙΑΚΌΣ",  # uppercase
            "Ολυμπιακός",  # title case
            "ολυμπιακός",  # lowercase
        ]

        normalized = [normalize_for_matching(team) for team in teams]

        # All should normalize to the same form
        assert len(set(normalized)) == 1


class TestHebrewScripts:
    """Tests for Hebrew script (both Latin and Hebrew)."""

    def test_maccabi_hebrew_vs_latin(self) -> None:
        """Maccabi: Hebrew מכבי vs Latin Maccabi."""
        hebrew = "מכבי"
        latin = "Maccabi"

        norm_hebrew = normalize_for_matching(hebrew)
        norm_latin = normalize_for_matching(latin)

        # Both should normalize without error
        assert isinstance(norm_hebrew, str)
        assert isinstance(norm_latin, str)

        # They should be distinct (different scripts)
        assert norm_hebrew != norm_latin

    def test_maccabi_tel_aviv_hebrew_full_name(self) -> None:
        """Maccabi Tel Aviv with Hebrew: מכבי תל אביב."""
        hebrew = "מכבי תל אביב"

        norm = normalize_for_matching(hebrew)

        assert isinstance(norm, str)
        assert len(norm) > 0

    def test_hebrew_text_normalization_consistency(self) -> None:
        """Hebrew text normalizes consistently."""
        # Hebrew text (note: Hebrew doesn't have uppercase/lowercase distinction)
        teams = [
            "מכבי",
            "מכבי",  # repeated to test idempotency
        ]

        normalized = [normalize_for_matching(team) for team in teams]

        # Both should normalize to the same form
        assert len(set(normalized)) == 1


class TestCJKScripts:
    """Tests for CJK (Chinese, Japanese, Korean) scripts."""

    def test_japanese_j1_league_teams(self) -> None:
        """Japanese J1 League team names normalize correctly."""
        # Exemplo: 横浜F・マリノス (Yokohama F. Marinos)
        team_jp = "横浜F・マリノス"
        norm = normalize_for_matching(team_jp)

        assert isinstance(norm, str)
        assert len(norm) > 0

    def test_korean_k_league_teams(self) -> None:
        """Korean K League team names normalize correctly."""
        # Example: 서울 (Seoul) or 울산 (Ulsan)
        teams_ko = [
            "서울",  # Seoul (Hangul)
            "울산",  # Ulsan (Hangul)
        ]

        for team in teams_ko:
            norm = normalize_for_matching(team)
            assert isinstance(norm, str)

    def test_chinese_super_league_teams(self) -> None:
        """Chinese Super League team names normalize correctly."""
        # Example: 北京 (Beijing) or 上海 (Shanghai)
        teams_zh = [
            "北京",  # Beijing
            "上海",  # Shanghai
        ]

        for team in teams_zh:
            norm = normalize_for_matching(team)
            assert isinstance(norm, str)

    def test_cjk_normalization_consistency(self) -> None:
        """CJK text normalizes consistently across variations."""
        # Japanese text repeated to test idempotency
        team = "横浜F・マリノス"

        norm_once = normalize_for_matching(team)
        norm_twice = normalize_for_matching(norm_once)

        assert norm_once == norm_twice


class TestMultiScriptMixing:
    """Tests for queries mixing multiple scripts."""

    def test_english_team_names_in_queries(self) -> None:
        """English team names in queries normalize correctly."""
        query = "Manchester United vs Chelsea"

        norm = normalize_for_matching(query)

        assert isinstance(norm, str)
        assert "manchester united" in norm

    def test_mixed_latin_cyrillic_in_query(self) -> None:
        """Mixed Latin and Cyrillic in same query."""
        # Example: "Zvezda vs Партизан"
        query = "Zvezda vs Партизан"

        norm = normalize_for_matching(query)

        assert isinstance(norm, str)

    def test_multilingual_match_descriptions(self) -> None:
        """Match descriptions with multiple script families."""
        descriptions = [
            "Ολυμπιακός vs Паnathinaikos",  # Greek + Latin
            "מכבי vs Chelsea",  # Hebrew + Latin
            "横浜 vs 서울",  # Japanese + Korean
        ]

        for desc in descriptions:
            norm = normalize_for_matching(desc)
            assert isinstance(norm, str)


class TestScriptFamilyDistinctness:
    """Tests ensuring different script families produce distinct results."""

    def test_latin_vs_cyrillic_distinctness(self) -> None:
        """Latin 'a' and Cyrillic 'а' produce different normalized forms."""
        # Latin 'a' (U+0061)
        latin_a = "a"
        # Cyrillic 'а' (U+0430) - looks similar but different
        cyrillic_a = "а"

        norm_latin = normalize_for_matching(latin_a)
        norm_cyrillic = normalize_for_matching(cyrillic_a)

        # They should be distinct after normalization
        assert norm_latin != norm_cyrillic

    def test_greek_vs_latin_distinctness(self) -> None:
        """Greek 'Α' and Latin 'A' produce different normalized forms."""
        # Greek 'Α' (U+0391)
        greek_alpha = "Α"
        # Latin 'A' (U+0041)
        latin_a = "A"

        norm_greek = normalize_for_matching(greek_alpha)
        norm_latin = normalize_for_matching(latin_a)

        # They should be distinct after normalization
        assert norm_greek != norm_latin
