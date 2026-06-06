"""Proof tests for Phase 10 §10.29.2 vowel-drop-before-suffix restoration."""
from __future__ import annotations

from nlp.vowel_drop_before_suffix import (
    load_vowel_drop_before_suffix_rules,
    tolerate_vowel_drop_before_suffix,
    validate_vowel_drop_before_suffix_coverage,
)
from nlp.normalize import normalize_input
from nlp.vendor.symspell import SymSpellIndex
from nlp.lexicon_loader import AliasHit


def test_load_vowel_drop_before_suffix_rules_successfully() -> None:
    rules = load_vowel_drop_before_suffix_rules()
    assert len(rules) >= 5
    assert any(rule.stem == "oğul" for rule in rules)
    assert any("accusative" in rule.suffix_classes for rule in rules)


def test_tolerates_vowel_drop_before_suffix_for_known_drop() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("oğulu", AliasHit("oğulu", "unknown", "1.0.0"))

    repaired, event = tolerate_vowel_drop_before_suffix("oğlu", idx.lookup)

    assert repaired == "oğulu"
    assert event is not None
    assert event["kind"] == "vowel_drop_repaired"
    assert event["original"] == "oğlu"
    assert event["repaired"] == "oğulu"


def test_does_not_repair_when_suffix_class_is_not_allowed() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("oğulun", AliasHit("oğulun", "unknown", "1.0.0"))

    repaired, event = tolerate_vowel_drop_before_suffix("oğlu", idx.lookup)

    assert repaired == "oğlu"
    assert event is None


def test_vowel_drop_before_suffix_step_runs_in_pipeline() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("burunu", AliasHit("burunu", "unknown", "1.0.0"))

    result = normalize_input(
        "burnu",
        _consonant_alternation_lookup=idx.lookup,
        _vowel_drop_before_suffix_lookup=idx.lookup,
    )

    assert "vowel_drop_before_suffix" in result.steps_run
    assert result.vowel_drop_before_suffix_events
    assert result.tokens[0] == "burunu"


def test_vowel_drop_before_suffix_corpus_repairs_match_expected() -> None:
    corpus = [
        {"surface": "oğlu", "canonical": "oğulu"},
        {"surface": "burnu", "canonical": "burunu"},
        {"surface": "ağzı", "canonical": "ağızı"},
        {"surface": "omzu", "canonical": "omuzu"},
        {"surface": "boynu", "canonical": "boyunu"},
        {"surface": "burna", "canonical": "buruna"},
        {"surface": "boyna", "canonical": "boyuna"},
    ]
    idx = SymSpellIndex(max_edit_distance=2)
    for row in corpus:
        idx.add_term(row["canonical"], AliasHit(row["canonical"], "unknown", "1.0.0"))

    for row in corpus:
        repaired, _ = tolerate_vowel_drop_before_suffix(row["surface"], idx.lookup)
        assert repaired == row["canonical"], f"{row['surface']} -> {repaired}"


def test_validate_vowel_drop_before_suffix_coverage_reports_missing_entries() -> None:
    errors = validate_vowel_drop_before_suffix_coverage(["oğul", "ankr"])
    assert errors == [
        "vowel_drop_before_suffix.tr.yaml missing required LeagueCatalog stem 'ankr'"
    ]
