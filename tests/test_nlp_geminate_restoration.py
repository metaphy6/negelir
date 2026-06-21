"""Tests for Phase 10 §10.29.1 geminate restoration support."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings, strategies as st

from nlp.geminate_restoration import (
    GeminateRestorationRule,
    load_geminate_restorations,
    restore_geminate,
)
from nlp.lexicon_loader import AliasHit
from nlp.normalize import normalize_input
from nlp.vendor.symspell import SymSpellIndex

_GEMINATE_SUFFIXES = (
    "ı",
    "ına",
    "ıyla",
    "ını",
    "ım",
    "ımı",
)
_GEMINATE_STEMS = (
    ("hak", "hakk"),
    ("sır", "sırr"),
    ("his", "hiss"),
    ("zan", "zann"),
    ("şık", "şıkk"),
)
_POSITIVE_GEMINATE_TOKENS = tuple(
    f"{doubled}{suffix}"
    for _, doubled in _GEMINATE_STEMS
    for suffix in _GEMINATE_SUFFIXES
)
_NEGATIVE_GEMINATE_TOKENS = (
    "golü",
    "topu",
    "bankı",
    "gollü",
    "toppu",
    "sahası",
    "maçı",
    "futbolu",
    "çayı",
    "şarkı",
    "bilimi",
    "kapısı",
    "çıkışı",
    "yapımı",
    "parası",
)


def test_loads_geminate_restoration_rules_successfully() -> None:
    rules = load_geminate_restorations()
    assert len(rules) == 5
    assert {rule.stem for rule in rules} == {
        "hak",
        "sır",
        "his",
        "zan",
        "şık",
    }
    assert all(isinstance(rule, GeminateRestorationRule) for rule in rules)


def test_restore_geminate_event_emitted_for_known_double_form() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("hakkı", AliasHit("hak", "unknown", "1.0.0"))
    repaired, event = restore_geminate(
        "hakkı",
        idx.lookup,
        restorations=load_geminate_restorations(),
    )
    assert repaired == "hakkı"
    assert event is not None
    assert event["kind"] == "geminate_restoration"
    assert event["stem"] == "hak"
    assert event["doubled_form"] == "hakk"


def test_normalize_input_includes_geminate_restoration_step() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("hakkı", AliasHit("hak", "unknown", "1.0.0"))

    result = normalize_input(
        "hakkı",
        _consonant_alternation_lookup=idx.lookup,
        _geminate_restoration_lookup=idx.lookup,
        _geminate_restoration_rules=load_geminate_restorations(),
        _clock=lambda: 0.0,
    )

    assert "geminate_restoration" in result.steps_run
    assert result.geminate_restoration_events == (
        {
            "kind": "geminate_restoration",
            "original": "hakkı",
            "stem": "hak",
            "doubled_form": "hakk",
            "source": "arabic",
        },
    )


@pytest.fixture(scope="module")
def symspell_index() -> SymSpellIndex:
    idx = SymSpellIndex(max_edit_distance=2)
    for term in _POSITIVE_GEMINATE_TOKENS + _NEGATIVE_GEMINATE_TOKENS:
        idx.add_term(term, AliasHit(term, "unknown", "1.0.0"))
    return idx


def test_geminate_restoration_positive_corpus_restores_known_forms(symspell_index: SymSpellIndex) -> None:
    rules = load_geminate_restorations()
    assert len(_POSITIVE_GEMINATE_TOKENS) >= 30
    for token in _POSITIVE_GEMINATE_TOKENS:
        repaired, event = restore_geminate(token, symspell_index.lookup, restorations=rules)
        assert repaired == token
        assert event is not None, f"no restoration event for {token}"
        assert event["kind"] == "geminate_restoration"
        assert event["original"] == token
        assert event["stem"] in {stem for stem, _ in _GEMINATE_STEMS}


def test_geminate_restoration_negative_corpus_does_not_restore(symspell_index: SymSpellIndex) -> None:
    rules = load_geminate_restorations()
    assert len(_NEGATIVE_GEMINATE_TOKENS) >= 15
    for token in _NEGATIVE_GEMINATE_TOKENS:
        repaired, event = restore_geminate(token, symspell_index.lookup, restorations=rules)
        assert repaired == token
        assert event is None, f"unexpected restoration event for {token}"


@given(st.sampled_from(_POSITIVE_GEMINATE_TOKENS + _NEGATIVE_GEMINATE_TOKENS))
@settings(max_examples=500)
def test_restore_geminate_is_idempotent(token: str) -> None:
    rules = load_geminate_restorations()
    idx = SymSpellIndex(max_edit_distance=2)
    for term in _POSITIVE_GEMINATE_TOKENS + _NEGATIVE_GEMINATE_TOKENS:
        idx.add_term(term, AliasHit(term, "unknown", "1.0.0"))

    repaired, _ = restore_geminate(token, idx.lookup, restorations=rules)
    repaired_again, _ = restore_geminate(repaired, idx.lookup, restorations=rules)
    assert repaired_again == repaired


def test_player_geminate_restoration_coverage_includes_doubled_consonant_names() -> None:
    from xops.makefile.nlp import _validate_player_geminate_restoration_coverage

    players_path = Path(__file__).resolve().parents[1] / "nlp" / "lexicon" / "players.tr.yaml"
    data = yaml.safe_load(players_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    assert isinstance(entries, list)

    errors = _validate_player_geminate_restoration_coverage({"players.tr.yaml": entries})
    assert errors == []
