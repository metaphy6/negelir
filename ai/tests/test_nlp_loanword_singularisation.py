from nlp.loanword_singularisation import (
    load_loanword_singularisation_rules,
    singularise_loanword_plural,
)
from nlp.normalize import normalize_input
from nlp.vendor.symspell import SymSpellIndex
from nlp.lexicon_loader import AliasHit


def test_load_loanword_singularisation_rules_successfully() -> None:
    rules = load_loanword_singularisation_rules()
    assert any(rule.loan_form == "link" and rule.accepted_plural == "linkler" for rule in rules)
    assert any(rule.loan_form == "data" and rule.accepted_plural == "datalar" for rule in rules)


def test_singularises_known_loanword_plural() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("link", AliasHit("link", "unknown", "1.0.0"))

    repaired, event = singularise_loanword_plural("linkler", idx.lookup)

    assert repaired == "link"
    assert event is not None
    assert event["kind"] == "loanword_singularised"
    assert event["accepted_plural"] == "linkler"
    assert event["loan_form"] == "link"


def test_does_not_singularise_unrelated_token() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("link", AliasHit("link", "unknown", "1.0.0"))

    repaired, event = singularise_loanword_plural("galatasaray", idx.lookup)

    assert repaired == "galatasaray"
    assert event is None


def test_loanword_singularisation_step_runs_in_pipeline() -> None:
    idx = SymSpellIndex(max_edit_distance=2)
    idx.add_term("data", AliasHit("data", "unknown", "1.0.0"))

    result = normalize_input(
        "datalar",
        _loanword_singularisation_lookup=idx.lookup,
    )

    assert "loanword_singularisation" in result.steps_run
    assert result.loanword_singularisation_events
    assert result.tokens[0] == "data"


def test_loanword_singularisation_corpus_repairs_match_expected() -> None:
    corpus = [
        {"surface": "linkler", "canonical": "link"},
        {"surface": "datalar", "canonical": "data"},
        {"surface": "mailler", "canonical": "mail"},
    ]

    idx = SymSpellIndex(max_edit_distance=2)
    for row in corpus:
        idx.add_term(row["canonical"], AliasHit(row["canonical"], "unknown", "1.0.0"))

    for row in corpus:
        repaired, _ = singularise_loanword_plural(row["surface"], idx.lookup)
        assert repaired == row["canonical"], f"{row['surface']} -> {repaired}"
