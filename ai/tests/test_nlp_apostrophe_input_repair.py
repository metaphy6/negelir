"""Tests for Phase 10 §10.32.5 input-side apostrophe repair."""
from __future__ import annotations

from nlp.apostrophe_proper_noun import (
    ApostropheRepair,
    repair_apostrophe_proper_noun,
)


def test_missing_apostrophe_suffix_rewrites_proper_noun() -> None:
    normalized, repairs = repair_apostrophe_proper_noun("Galatasaraya")
    assert normalized == "galatasaray'a"
    assert repairs == (
        ApostropheRepair(
            original="galatasaraya",
            repaired="galatasaray'a",
            rule_id="missing_apostrophe_suffix",
            rule_class="missing_apostrophe_suffix",
        ),
    )


def test_misplaced_apostrophe_repairs_single_candidate() -> None:
    normalized, repairs = repair_apostrophe_proper_noun("Galat'asaraya")
    assert normalized == "galatasaray'a"
    assert repairs == (
        ApostropheRepair(
            original="galat'asaraya",
            repaired="galatasaray'a",
            rule_id="misplaced_apostrophe",
            rule_class="misplaced_apostrophe",
        ),
    )


def test_legitimate_internal_apostrophe_is_preserved() -> None:
    normalized, repairs = repair_apostrophe_proper_noun("akhisar'spor")
    assert normalized == "akhisar'spor"
    assert repairs == ()


def test_normalize_pipeline_apostrophe_repair_step_runs() -> None:
    from nlp.normalize import normalize_input

    result = normalize_input("Galatasaraya maç")
    assert "apostrophe_proper_noun_repair" in result.steps_run
    assert "galatasaray'a" in result.tokens
    assert result.apostrophe_repairs


def test_correct_apostrophe_input_idempotent() -> None:
    normalized, repairs = repair_apostrophe_proper_noun("galatasaray'a")
    assert normalized == "galatasaray'a"
    assert repairs == ()
