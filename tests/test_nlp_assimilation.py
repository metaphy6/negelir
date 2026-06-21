"""Proof tests for Phase 10 §10.28.2 assimilation folding."""
from __future__ import annotations

from pathlib import Path
import json

import pytest

from nlp.assimilation import (
    fold_assimilated_suffixes,
    load_assimilation_pairs,
)
from nlp.normalize import normalize_input
from nlp.vendor.symspell import SymSpellIndex
from nlp.lexicon_loader import AliasHit


class TestAssimilationRules:
    def test_loads_assimilation_pairs(self) -> None:
        rules = load_assimilation_pairs()
        assert rules.voiced == ('de', 'da', 'den', 'dan')
        assert rules.voiceless == ('te', 'ta', 'ten', 'tan')
        assert rules.instrumental_short == ('le', 'la')
        assert rules.instrumental_canonical == ('yle', 'yla')

    def test_folds_voiceless_locative_forms(self) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        for term in ('futbolda', 'galatasarayda', 'akşamda', 'evde', 'şehirde'):
            idx.add_term(term, AliasHit(term, 'unknown', '1.0.0'))

        repaired = fold_assimilated_suffixes(
            ['futbolta', 'galatasarayta', 'akşamte', 'evte', 'şehirte'],
            idx.lookup,
            load_assimilation_pairs(),
        )
        assert repaired == ['futbolda', 'galatasarayda', 'akşamda', 'evde', 'şehirde']

    def test_folds_vowel_final_instrumental_short_forms(self) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        for term in ('kediyle', 'arabayla'):
            idx.add_term(term, AliasHit(term, 'unknown', '1.0.0'))

        repaired = fold_assimilated_suffixes(
            ['kedile', 'arabale'],
            idx.lookup,
            load_assimilation_pairs(),
        )
        assert repaired == ['kediyle', 'arabayla']

    def test_skips_exact_dictionary_entries(self) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term('nokta', AliasHit('nokta', 'unknown', '1.0.0'))

        repaired = fold_assimilated_suffixes(['nokta'], idx.lookup, load_assimilation_pairs())
        assert repaired == ['nokta']


class TestAssimilationCorpus:
    @pytest.fixture(scope='class')
    def corpus(self) -> list[dict[str, str]]:
        path = Path(__file__).parent / 'fixtures' / 'assimilation_corpus.tr.json'
        with path.open('r', encoding='utf-8') as fh:
            return json.load(fh)

    def test_assimilation_corpus_has_forty_rows(self, corpus: list[dict[str, str]]) -> None:
        assert len(corpus) == 40

    def test_assimilation_corpus_matches_expected(self, corpus: list[dict[str, str]]) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        for entry in corpus:
            idx.add_term(entry['canonical'], AliasHit(entry['canonical'], 'unknown', '1.0.0'))

        repaired = fold_assimilated_suffixes(
            [entry['surface'] for entry in corpus],
            idx.lookup,
            load_assimilation_pairs(),
        )
        assert repaired == [entry['canonical'] for entry in corpus]

    def test_assimilation_fold_runs_in_pipeline(self) -> None:
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term('galatasarayda', AliasHit('galatasarayda', 'unknown', '1.0.0'))

        result = normalize_input(
            'galatasarayta',
            _assimilation_lookup=idx.lookup,
            _assimilation_pairs=load_assimilation_pairs(),
        )
        assert 'assimilation_fold' in result.steps_run
        assert result.tokens == ('galatasarayda',)
