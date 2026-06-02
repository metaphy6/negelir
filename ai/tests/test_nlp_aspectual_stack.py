"""Tests for Phase 10 §10.32.2 aspectual-stack detection."""
from __future__ import annotations

from hypothesis import given, strategies as st

from nlp.aspectual_stack import detect_aspectual_stack, load_aspectual_stack_rules

ASPECTUAL_STACK_PROOF_SAMPLES = [
    ("yenmiş olacak", "future_perfect_evidential"),
    ("yenmiş olacaksa", "future_perfect_evidential"),
    ("gelmiş olacak", "future_perfect_evidential"),
    ("gelmiş olacaksa", "future_perfect_evidential"),
    ("kazanmış olacak", "future_perfect_evidential"),
    ("kazanmış olacaksa", "future_perfect_evidential"),
    ("bitmiş olacak", "future_perfect_evidential"),
    ("bitmiş olacaksa", "future_perfect_evidential"),
    ("oynamış olabilir", "perfect_modal_potential"),
    ("kazanmış olabilir", "perfect_modal_potential"),
    ("gelmiş olabilir", "perfect_modal_potential"),
    ("bitmiş olabilir", "perfect_modal_potential"),
    ("yenmiş olabilir", "perfect_modal_potential"),
    ("gol atılmış olabilir", "perfect_modal_potential"),
    ("başlamak üzere", "imminent_progressive"),
    ("girmek üzere", "imminent_progressive"),
    ("bitecek üzere", "imminent_progressive"),
    ("başlayacak üzere", "imminent_progressive"),
    ("oynayacak üzere", "imminent_progressive"),
    ("kalkmak üzere", "imminent_progressive"),
    ("oynuyor olabilir", "progressive_epistemic"),
    ("kazanıyor olabilir", "progressive_epistemic"),
    ("bitiyor olabilir", "progressive_epistemic"),
    ("gidiyor olabilir", "progressive_epistemic"),
    ("geliyor olabilir", "progressive_epistemic"),
    ("oluyor olabilir", "progressive_epistemic"),
    ("oynayacak olan kim", "future_relative_clause_attributive"),
    ("kazanacak olan kim", "future_relative_clause_attributive"),
    ("gelecek olan kim", "future_relative_clause_attributive"),
    ("yapacak olan kim", "future_relative_clause_attributive"),
    ("girecek olan kim", "future_relative_clause_attributive"),
    ("bitirecek olan kim", "future_relative_clause_attributive"),
    ("oynamış olur", "progressive_inferential"),
    ("oynamış olursa", "progressive_inferential"),
    ("kazanmış olur", "progressive_inferential"),
    ("kazanmış olursa", "progressive_inferential"),
    ("gelmiş olur", "progressive_inferential"),
    ("gelmiş olursa", "progressive_inferential"),
    ("bitmiş olur", "progressive_inferential"),
    ("bitmiş olursa", "progressive_inferential"),
    ("maç bitmiş olur", "progressive_inferential"),
    ("takım kazanmış olur", "progressive_inferential"),
    ("attaş olmuş olabilir", "perfect_modal_potential"),
    ("takım gelmiş olacaksa", "future_perfect_evidential"),
    ("maç oynuyor olabilir", "progressive_epistemic"),
    ("hazırlık başlamak üzere", "imminent_progressive"),
    ("takım girecek olan kim", "future_relative_clause_attributive"),
    ("kim gelecek olan var", "future_relative_clause_attributive"),
    ("galiba kazanmış olabilir", "perfect_modal_potential"),
    ("yakında bitecek üzere", "imminent_progressive"),
]


def test_loads_aspectual_stack_rules_from_yaml() -> None:
    rules = load_aspectual_stack_rules()
    assert len(rules) == 6
    classes = {rule.modality_class for rule in rules}
    assert classes == {
        "future_perfect_evidential",
        "perfect_modal_potential",
        "imminent_progressive",
        "progressive_epistemic",
        "future_relative_clause_attributive",
        "progressive_inferential",
    }


def test_detects_future_perfect_evidential_stack() -> None:
    detection = detect_aspectual_stack("yenmiş olacak")
    assert detection is not None
    assert detection.modality_class == "future_perfect_evidential"


def test_detects_progressive_inferential_stack() -> None:
    detection = detect_aspectual_stack("kazanmış olur")
    assert detection is not None
    assert detection.modality_class == "progressive_inferential"


def test_detects_future_relative_clause_attributive_stack() -> None:
    detection = detect_aspectual_stack("oynayacak olan kim")
    assert detection is not None
    assert detection.modality_class == "future_relative_clause_attributive"


def test_detects_conditional_aspectual_stack_with_olacaksa() -> None:
    detection = detect_aspectual_stack("eğer yenmiş olacaksa")
    assert detection is not None
    assert detection.modality_class == "future_perfect_evidential"


def test_aspectual_stack_golden_corpus_contains_fifty_examples() -> None:
    assert len(ASPECTUAL_STACK_PROOF_SAMPLES) == 50


@given(st.sampled_from(ASPECTUAL_STACK_PROOF_SAMPLES))
def test_aspectual_stack_golden_corpus_examples_are_deterministic(
    sample: tuple[str, str],
) -> None:
    text, expected_modality = sample
    detection = detect_aspectual_stack(text)
    assert detection is not None
    assert detection.modality_class == expected_modality
