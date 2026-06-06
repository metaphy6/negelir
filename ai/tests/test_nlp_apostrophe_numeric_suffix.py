"""Phase 10 §10.32.7 — Apostrophe-suffixed numeric token parsing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nlp.normalize import normalize_input
from nlp.numbers.apostrophe_suffixed import (
    load_numeric_apostrophe_spec,
    numeric_apostrophe_spec_sha256,
    parse_apostrophe_suffixed_numeric,
)


def test_parse_numeric_apostrophe_cardinal_accusative() -> None:
    parsed = parse_apostrophe_suffixed_numeric("3'ü")
    assert parsed == {
        "value": 3,
        "kind": "cardinal",
        "case": "accusative",
    }


def test_parse_numeric_apostrophe_score_pair_derivative_lik() -> None:
    parsed = parse_apostrophe_suffixed_numeric("1-1'lik")
    assert parsed == {
        "value": (1, 1),
        "kind": "score_pair",
        "case": "derivative_lik",
    }


def test_parse_numeric_apostrophe_ordinal_genitive() -> None:
    parsed = parse_apostrophe_suffixed_numeric("100.'sü")
    assert parsed == {
        "value": 100,
        "kind": "ordinal",
        "case": "genitive",
    }


def test_normalize_input_emits_numeric_apostrophe_event() -> None:
    result = normalize_input("3'ü")
    events = [event for event in result.normalization_events if event.get("kind") == "numeric_apostrophe_suffix"]
    assert len(events) == 1
    assert events[0]["token"] == "3'ü"
    assert events[0]["parse"] == {
        "value": 3,
        "kind": "cardinal",
        "case": "accusative",
    }


def test_numeric_apostrophe_spec_is_shared_single_source() -> None:
    spec = load_numeric_apostrophe_spec()
    assert isinstance(spec, dict)
    assert "shape_regex" in spec
    assert "case_map" in spec
    spec_path = Path(__file__).resolve().parents[2] / "ai" / "common" / "text" / "numeric_apostrophe_spec.json"
    expected_hash = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    assert numeric_apostrophe_spec_sha256(spec_path) == expected_hash


def test_numerical_apostrophe_golden_sample_parses_all_variants() -> None:
    positives = {
        "3'ü": {"value": 3, "kind": "cardinal", "case": "accusative"},
        "2'ı": {"value": 2, "kind": "cardinal", "case": "accusative"},
        "77'u": {"value": 77, "kind": "cardinal", "case": "accusative"},
        "42'ın": {"value": 42, "kind": "cardinal", "case": "genitive"},
        "10.'un": {"value": 10, "kind": "ordinal", "case": "genitive"},
        "20.'ün": {"value": 20, "kind": "ordinal", "case": "genitive"},
        "5'te": {"value": 5, "kind": "cardinal", "case": "locative"},
        "8'de": {"value": 8, "kind": "cardinal", "case": "locative"},
        "11'da": {"value": 11, "kind": "cardinal", "case": "locative"},
        "12'te": {"value": 12, "kind": "cardinal", "case": "locative"},
        "50'ten": {"value": 50, "kind": "cardinal", "case": "ablative"},
        "60'tan": {"value": 60, "kind": "cardinal", "case": "ablative"},
        "70'den": {"value": 70, "kind": "cardinal", "case": "ablative"},
        "80'den": {"value": 80, "kind": "cardinal", "case": "ablative"},
        "1-1'lik": {"value": (1, 1), "kind": "score_pair", "case": "derivative_lik"},
        "2-2'lik": {"value": (2, 2), "kind": "score_pair", "case": "derivative_lik"},
        "3-3'lık": {"value": (3, 3), "kind": "score_pair", "case": "derivative_lik"},
        "4-4'lük": {"value": (4, 4), "kind": "score_pair", "case": "derivative_lik"},
        "5-0'luk": {"value": (5, 0), "kind": "score_pair", "case": "derivative_lik"},
        "6-5'lik": {"value": (6, 5), "kind": "score_pair", "case": "derivative_lik"},
        "7-7'lık": {"value": (7, 7), "kind": "score_pair", "case": "derivative_lik"},
        "8-9'lük": {"value": (8, 9), "kind": "score_pair", "case": "derivative_lik"},
        "9-8'luk": {"value": (9, 8), "kind": "score_pair", "case": "derivative_lik"},
        "10-10'lik": {"value": (10, 10), "kind": "score_pair", "case": "derivative_lik"},
        "100.'sü": {"value": 100, "kind": "ordinal", "case": "genitive"},
        "30.'a": {"value": 30, "kind": "ordinal", "case": "dative"},
        "40.'e": {"value": 40, "kind": "ordinal", "case": "dative"},
        "50.'de": {"value": 50, "kind": "ordinal", "case": "locative"},
        "60.'ta": {"value": 60, "kind": "ordinal", "case": "locative"},
        "70.'den": {"value": 70, "kind": "ordinal", "case": "ablative"},
        "80.'tan": {"value": 80, "kind": "ordinal", "case": "ablative"},
    }

    for token, expected in positives.items():
        parsed = parse_apostrophe_suffixed_numeric(token)
        assert parsed == expected, f"{token} parsed as {parsed}"

    negatives = ["5'", "123'abc", "1.5'de", "7--8'lik", "3'yu", "abc'ü"]
    for token in negatives:
        assert parse_apostrophe_suffixed_numeric(token) is None
