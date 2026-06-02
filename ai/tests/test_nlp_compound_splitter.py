"""Proof tests for Phase 10 §10.28.3 no-space compound splitting."""
from __future__ import annotations

import json
from pathlib import Path

from nlp.compound_splitter import split_compound_tokens
from nlp.vendor.symspell import SymSpellIndex
from nlp.lexicon_loader import AliasHit


class TestCompoundSplitter:
    @staticmethod
    def _make_lookup(terms: list[str]):
        idx = SymSpellIndex(max_edit_distance=2)
        for term in terms:
            idx.add_term(term, AliasHit(term, 'unknown', '1.0.0'))
        return idx.lookup

    def test_splits_known_compound_token(self) -> None:
        lookup = self._make_lookup(['galatasaray', 'fenerbahce', 'derbisi'])
        result = split_compound_tokens(
            ['galatasarayfenerbahcederbisi'],
            lookup,
            top_words={'galatasaray', 'fenerbahce', 'derbisi'},
            max_splits=4,
            max_lookups=24,
        )
        assert result == ['galatasaray', 'fenerbahce', 'derbisi']

    def test_does_not_split_ambiguous_suffix_residual(self) -> None:
        lookup = self._make_lookup(['galatasaray'])
        result = split_compound_tokens(
            ['galatasaraylılar'],
            lookup,
            top_words={'galatasaray'},
            max_splits=4,
            max_lookups=24,
        )
        assert result == ['galatasaraylılar']

    def test_skips_tokens_flagged_as_pii(self) -> None:
        lookup = self._make_lookup(['12345678901'])
        result = split_compound_tokens(
            ['12345678901'],
            lookup,
            top_words=set(),
            max_splits=4,
            max_lookups=24,
            skip_if_pii=lambda token: token == '12345678901',
        )
        assert result == ['12345678901']

    def test_applies_only_one_split_per_query(self) -> None:
        lookup = self._make_lookup(['galatasaray', 'fenerbahce', 'derbisi', 'bursaspor'])
        result = split_compound_tokens(
            ['galatasarayfenerbahcederbisi', 'bursaspor'],
            lookup,
            top_words={'galatasaray', 'fenerbahce', 'derbisi', 'bursaspor'},
            max_splits=4,
            max_lookups=24,
        )
        assert result == ['galatasaray', 'fenerbahce', 'derbisi', 'bursaspor']

    def test_corpus_splits_all_fixture_rows(self) -> None:
        fixture_path = Path(__file__).resolve().parent / 'fixtures' / 'compound_splitter_corpus.tr.json'
        presented = json.loads(fixture_path.read_text(encoding='utf-8'))
        lookup_terms = {
            term
            for row in presented
            for term in row['expected']
            if len(row['expected']) > 1
        }
        lookup = self._make_lookup(sorted(lookup_terms))
        top_words = {'bugun', 'mac', 'varmi', 'da', 'liga', 'gol', 'form', 'aktif'}

        for row in presented:
            result = split_compound_tokens(
                [row['input']],
                lookup,
                top_words=top_words,
                max_splits=4,
                max_lookups=24,
            )
            assert result == row['expected']

    def test_does_not_split_negative_corpus(self) -> None:
        lookup = self._make_lookup(['galatasaray', 'fenerbahce', 'derbisi'])
        negative_inputs = [
            'galatasaraylılar',
            'fenerbahceliyiz',
            'ankarasporum',
            'trabzonsporlu',
            'superligde',
            'istanbuler',
            'macchik',
            'bugunmacimiz',
            'polatlioglu',
            'ankaraistanbul',
        ]
        for token in negative_inputs:
            result = split_compound_tokens(
                [token],
                lookup,
                top_words={'bugun', 'mac', 'varmi'},
                max_splits=4,
                max_lookups=24,
            )
            assert result == [token]
