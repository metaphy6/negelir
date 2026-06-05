"""Tests for Phase 10 §10.32.5 input-side apostrophe repair."""
from __future__ import annotations

from nlp.apostrophe_proper_noun import (
    ApostropheRepair,
    load_proper_noun_apostrophe_spec,
    load_proper_noun_apostrophe_suffix_forms,
    proper_noun_apostrophe_spec_sha256,
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
            evidence="lexicon_prefix_match",
        ),
    )


def test_proper_noun_apostrophe_spec_is_shared_single_source() -> None:
    spec = load_proper_noun_apostrophe_spec()
    assert spec["_meta"]["schema_version"] == 1
    assert "genitive" == spec["suffix_families"][0]["name"]
    assert "akhisar'spor" in spec["internal_apostrophe_allowlist"]
    assert proper_noun_apostrophe_spec_sha256() == "935a0c430ff3c326c059bbb91e6a1aeb50e9abb1d4bdd63fdc326cf864927e4a"


def test_voice_path_does_not_short_circuit_on_capitalization_alone() -> None:
    normalized, repairs = repair_apostrophe_proper_noun(
        "Galatasaraya",
        input_source="voice",
    )
    assert normalized == "galatasaraya"
    assert repairs == ()


def test_normalize_input_records_apostrophe_inference_event() -> None:
    from nlp.normalize import normalize_input

    result = normalize_input("Galatasaraya maç")
    assert result.apostrophe_repair_events == (
        {
            "kind": "apostrophe_inferred",
            "evidence": "lexicon_prefix_match",
            "original": "galatasaraya",
            "canonical": "galatasaray'a",
        },
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


def test_apostrophe_repair_golden_corpus() -> None:
    missing_apostrophe = {
        'Galatasaraya': "galatasaray'a",
        'Fenerbahçeye': "fenerbahçe'ye",
        'Beşiktaşa': "beşiktaş'a",
        'Trabzonspora': "trabzonspor'a",
        'Kasımpaşaya': "kasımpaşa'ya",
        'Antalyaspora': "antalyaspor'a",
        'Sivasspora': "sivasspor'a",
        'Göztepeye': "göztepe'ye",
        'Kayserispora': "kayserispor'a",
        'Başakşehire': "başakşehir'e",
        'Konyasporas': "konyaspor'a",
        'Bursasporay': "bursaspor'a",
        'Gaziantepe': "gaziantep'e",
        'Eskişehirspora': "eskişehirspor'a",
        'ÇaykurRizespora': "çaykurrizespor'a",
        'Malatyasporay': "malatyaspor'a",
        'Kocaelisporay': "kocaelispor'a",
        'Denizlisporay': "denizlispor'a",
        'Ispartasporay': "ıspartaspor'a",
        'Genclerbirligine': "gençlerbirliği'ne",
    }

    misplaced_apostrophe = {
        'Galat\'asaraya': "galatasaray'a",
        'Fenerbahç\'eye': "fenerbahçe'ye",
        'Beşikta\'şa': "beşiktaş'a",
        'Trabzonsp\'ora': "trabzonspor'a",
        'Kasımpa\'şaya': "kasımpaşa'ya",
        'Antalyasp\'ora': "antalyaspor'a",
        'Sivassp\'ora': "sivasspor'a",
        'Göztep\'eye': "göztepe'ye",
        'Kayserisp\'ora': "kayserispor'a",
        'Başakşehir\'e': "başakşehir'e",
        'Konyasp\'ora': "konyaspor'a",
        'Bursasp\'ora': "bursaspor'a",
        'Gaziantep\'e': "gaziantep'e",
        'Eskişehirsp\'ora': "eskişehirspor'a",
        'ÇaykurRizesp\'ora': "çaykurrizespor'a",
        'Malatyasp\'oray': "malatyaspor'a",
        'Kocaelisp\'oray': "kocaelispor'a",
        'Denizlisp\'oray': "denizlispor'a",
        'Ispartasp\'oray': "ıspartaspor'a",
        'Genclerbirlig\'ine': "gençlerbirliği'ne",
    }

    legitimate_internal = [
        "galatasaray'a",
        "fenerbahçe'ye",
        "beşiktaş'a",
        "trabzonspor'a",
        "kasımbaşa'ya",
        "antalyaspor'a",
        "sivasspor'a",
        "göztepe'ye",
        "kayserispor'a",
        "başakşehir'e",
        "konyaspor'a",
        "bursaspor'a",
        "gaziantep'e",
        "eskişehirspor'a",
        "çaykurrizespor'a",
        "malatyaspor'a",
        "kocaelispor'a",
        "denizlispor'a",
        "ıspartaspor'a",
        "akhisar'spor",
    ]

    for source, expected in missing_apostrophe.items():
        normalized, repairs = repair_apostrophe_proper_noun(source)
        assert normalized == expected
        assert repairs == (
            ApostropheRepair(
                original=source.lower(),
                repaired=expected,
                rule_id="missing_apostrophe_suffix",
                rule_class="missing_apostrophe_suffix",
                evidence="lexicon_prefix_match",
            ),
        )

    for source, expected in misplaced_apostrophe.items():
        normalized, repairs = repair_apostrophe_proper_noun(source)
        assert normalized == expected
        assert repairs == (
            ApostropheRepair(
                original=source.lower(),
                repaired=expected,
                rule_id="misplaced_apostrophe",
                rule_class="misplaced_apostrophe",
            ),
        )

    for source in legitimate_internal:
        normalized, repairs = repair_apostrophe_proper_noun(source)
        assert normalized == source
        assert repairs == ()


def test_apostrophe_repair_suffix_forms_are_idempotent() -> None:
    suffix_forms = load_proper_noun_apostrophe_suffix_forms()
    for suffix in suffix_forms:
        token = f"galatasaray'{suffix}"
        normalized, repairs = repair_apostrophe_proper_noun(token)
        assert normalized == token
        assert repairs == ()
