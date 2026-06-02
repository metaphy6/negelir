"""Proof tests for Phase 10 §10.28.1 consonant alternation tolerance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from nlp.consonant_alternation import (
    ConsonantAlternationRule,
    load_consonant_alternations,
    tolerate_consonant_alternation,
)
from nlp.normalize import normalize_input
from nlp.vendor.symspell import SymSpellIndex
from nlp.lexicon_loader import AliasHit


class TestConsonantAlternationRuleLoading:
    def test_rules_load_successfully(self) -> None:
        rules = load_consonant_alternations()
        assert len(rules) == 5
        assert {rule.stem for rule in rules} == {
            "kitap",
            "ağaç",
            "renk",
            "yaprak",
            "kılıç",
        }


class TestConsonantAlternationRepair:
    @pytest.fixture(scope="class")
    def symspell(self) -> SymSpellIndex:
        idx = SymSpellIndex(max_edit_distance=2)
        entries = [
            "kitabı",
            "kitabın",
            "kitaba",
            "ağacı",
            "ağacın",
            "ağaca",
            "rengi",
            "rengîn",
            "yaprağı",
            "yaprağın",
            "kılıcı",
            "kılıcın",
        ]
        for term in entries:
            idx.add_term(term, AliasHit(term, "unknown", "1.0.0"))
        return idx

    def test_tolerates_consonant_alternation_for_softening(self, symspell: SymSpellIndex) -> None:
        repaired = normalize_input(
            "kitapı",
            _consonant_alternation_lookup=symspell.lookup,
            _consonant_alternation_alternations=load_consonant_alternations(),
        )
        assert "consonant_alternation" in repaired.steps_run
        assert repaired.consonant_alternation_repairs == (("kitapı", "kitabı"),)
        assert repaired.consonant_alternation_events[0]["kind"] == "consonant_softening_repaired"
        assert repaired.tokens[0] == "kitabı"

    def test_skips_no_strip_canonical_tokens(self, symspell: SymSpellIndex) -> None:
        repaired = normalize_input(
            "eşikç",
            _consonant_alternation_lookup=symspell.lookup,
            _consonant_alternation_alternations=load_consonant_alternations(),
        )
        assert repaired.consonant_alternation_repairs == ()
        assert repaired.consonant_alternation_events == ()

    @given(st.sampled_from(load_consonant_alternations()))
    @settings(max_examples=500)
    def test_tolerate_consonant_alternation_is_idempotent(
        self,
        rule: ConsonantAlternationRule,
    ) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term(rule.stem, AliasHit(rule.stem, "unknown", "1.0.0"))

        repaired, event = tolerate_consonant_alternation(
            rule.stem,
            idx.lookup,
            no_strip_canonicals=set(),
            alternations=load_consonant_alternations(),
        )
        assert repaired == rule.stem
        assert event is None


class TestConsonantAlternationCorpus:
    @pytest.fixture(scope="class")
    def corpus(self) -> list[dict[str, str]]:
        path = Path(__file__).parent / "fixtures" / "consonant_alternation_corpus.tr.json"
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_golden_corpus_has_thirty_rows(self, corpus: list[dict[str, str]]) -> None:
        assert len(corpus) == 30

    def test_golden_corpus_repairs_match_expected(self, corpus: list[dict[str, str]]) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        canonical_terms = {entry["canonical"] for entry in corpus}
        for canonical in canonical_terms:
            idx.add_term(canonical, AliasHit(canonical, "unknown", "1.0.0"))

        alternations = load_consonant_alternations()
        for entry in corpus:
            token = entry["surface"]
            expected = entry["canonical"]
            repaired, _ = tolerate_consonant_alternation(
                token,
                idx.lookup,
                no_strip_canonicals=set(),
                alternations=alternations,
            )
            assert repaired == expected, f"{token} -> {repaired} (expected {expected})"

    def test_consonant_alternation_step_runs_in_pipeline(self) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term("kitabı", AliasHit("kitabı", "unknown", "1.0.0"))

        result = normalize_input(
            "kitapı",
            _consonant_alternation_lookup=idx.lookup,
            _consonant_alternation_alternations=load_consonant_alternations(),
        )
        assert "consonant_alternation" in result.steps_run
        assert result.consonant_alternation_repairs
        assert result.consonant_alternation_events[0]["kind"] == "consonant_softening_repaired"

