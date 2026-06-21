"""Phase 10 §10.26.10 — Football vocabulary hint and verification coverage."""
from __future__ import annotations

import sys
from pathlib import Path

from common.config import cfg

# Make sure ai/ and repo root are importable when tests run from REPO_ROOT.
_AI_DIR = Path(__file__).parent.parent
_REPO_ROOT = _AI_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))


def test_football_vocab_loader_reads_table() -> None:
    from nlp.football_vocab import load_football_vocab

    entries = load_football_vocab()
    assert any(entry.canonical_concept == "handicap" for entry in entries)
    handicap_entry = next(entry for entry in entries if entry.canonical_concept == "handicap")
    assert "handikap" in handicap_entry.surface_forms_tr
    assert "handicap" in handicap_entry.surface_forms_en
    assert handicap_entry.intent_hint == "predict.handicap"


def test_football_vocab_hint_prefixes_classifier_input(monkeypatch) -> None:
    from nlp.intent import IntentClassifier

    class DummyModel:
        def __init__(self) -> None:
            self.last_text: str | None = None

        def predict(self, text: str, k: int = 1):
            self.last_text = text
            return (["__label__predict.handicap"], [0.9])

    monkeypatch.setattr(cfg, "nlp_football_vocab_hints_enabled", True)
    classifier = IntentClassifier(DummyModel(), Path("dummy"), None, "", None, "")

    label, prob = classifier.predict_intent("handikap kuponu")
    assert classifier._model.last_text is not None
    assert classifier._model.last_text.startswith("__concept_handicap__")
    assert label == "predict.handicap"
    assert prob == 0.9


def test_football_vocab_hint_prefixes_classifier_input_for_english_surface_form(monkeypatch) -> None:
    from nlp.intent import IntentClassifier

    class DummyModel:
        def __init__(self) -> None:
            self.last_text: str | None = None

        def predict(self, text: str, k: int = 1):
            self.last_text = text
            return (["__label__predict.btts"], [0.85])

    monkeypatch.setattr(cfg, "nlp_football_vocab_hints_enabled", True)
    classifier = IntentClassifier(DummyModel(), Path("dummy"), None, "", None, "")

    label, prob = classifier.predict_intent("both teams to score")
    assert classifier._model.last_text is not None
    assert classifier._model.last_text.startswith("__concept_btts__")
    assert label == "predict.btts"
    assert prob == 0.85


def test_football_vocab_hint_skips_prefix_for_unrelated_text(monkeypatch) -> None:
    from nlp.intent import IntentClassifier

    class DummyModel:
        def __init__(self) -> None:
            self.last_text: str | None = None

        def predict(self, text: str, k: int = 1):
            self.last_text = text
            return (["__label__predict.match_outcome"], [0.88])

    monkeypatch.setattr(cfg, "nlp_football_vocab_hints_enabled", True)
    classifier = IntentClassifier(DummyModel(), Path("dummy"), None, "", None, "")

    label, prob = classifier.predict_intent("kim kazanacak")
    assert classifier._model.last_text == "kim kazanacak"
    assert label == "predict.match_outcome"
    assert prob == 0.88


def test_football_vocab_hint_disabled_skips_prefix(monkeypatch) -> None:
    from nlp.intent import IntentClassifier

    class DummyModel:
        def __init__(self) -> None:
            self.last_text: str | None = None

        def predict(self, text: str, k: int = 1):
            self.last_text = text
            return (["__label__predict.handicap"], [0.9])

    monkeypatch.setattr(cfg, "nlp_football_vocab_hints_enabled", False)
    classifier = IntentClassifier(DummyModel(), Path("dummy"), None, "", None, "")

    classifier.predict_intent("handikap kuponu")
    assert classifier._model.last_text == "handikap kuponu"


def test_verify_nlp_football_vocab_command_passes() -> None:
    from xops.makefile import nlp as nlp_make

    assert nlp_make.cmd_verify_nlp_football_vocab([]) == 0
