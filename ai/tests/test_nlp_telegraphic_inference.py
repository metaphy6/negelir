from __future__ import annotations

from types import MethodType

from nlp.intent import IntentClassifier, IntentScore
from nlp.phase10_30 import infer_telegraphic_intent


def test_infer_telegraphic_intent_routes_fixture_lookup_for_temporal_query() -> None:
    entities = [
        {"kind": "team", "confidence": 0.92, "source": "gazetteer"},
        {"kind": "date", "confidence": 0.99, "source": "ner"},
    ]
    label, calibrated_prob, source = infer_telegraphic_intent(
        entities=entities,
        intent_distribution=None,
        normalized_text="galatasaray bugün",
        token_count=3,
        has_verb_form=False,
    )

    assert label == "data.fixture_lookup"
    assert calibrated_prob == 0.65
    assert source == "telegraphic_inference"


def test_infer_telegraphic_intent_skips_predict_intents() -> None:
    entities = [
        {"kind": "team", "confidence": 0.95, "source": "gazetteer"},
        {"kind": "date", "confidence": 0.95, "source": "ner"},
    ]
    distribution = [
        {"label": "predict.match_outcome", "raw_prob": 0.92, "calibrated_prob": 0.92},
        {"label": "data.fixture_lookup", "raw_prob": 0.08, "calibrated_prob": 0.08},
    ]

    label, calibrated_prob, source = infer_telegraphic_intent(
        entities=entities,
        intent_distribution=distribution,
        normalized_text="stadium bugün",
        token_count=2,
        has_verb_form=False,
    )

    assert label == "data.fixture_lookup"
    assert source == "telegraphic_inference"
    assert calibrated_prob == 0.65


def test_intent_classifier_classify_uses_telegraphic_inference_when_eligible() -> None:
    classifier = IntentClassifier.__new__(IntentClassifier)
    classifier._calibration = None

    def fake_predict(self, text: str, k: int = 3):
        return [
            IntentScore(
                label="predict.match_outcome",
                raw_prob=0.95,
                calibrated_prob=0.95,
                raw_logit=None,
                raw_logit_after_wh_prior=None,
            )
        ]

    classifier.predict_intent_distribution = MethodType(fake_predict, classifier)

    result = classifier.classify(
        text="galatasaray bugün",
        min_conf=0.95,
        entities=[
            {"kind": "team", "confidence": 0.9, "source": "gazetteer"},
            {"kind": "date", "confidence": 0.9, "source": "ner"},
        ],
        has_verb_form=False,
    )

    assert result.label == "data.fixture_lookup"
    assert result.calibrated_prob == 0.65


def test_nlp_telegraphic_inference_never_routes_predict() -> None:
    entities = [
        {"kind": "team", "confidence": 0.95, "source": "gazetteer"},
        {"kind": "date", "confidence": 0.95, "source": "ner"},
    ]
    distribution = [
        {"label": "predict.match_outcome", "raw_prob": 0.90, "calibrated_prob": 0.90},
        {"label": "data.fixture_lookup", "raw_prob": 0.10, "calibrated_prob": 0.10},
    ]

    label, calibrated_prob, source = infer_telegraphic_intent(
        entities=entities,
        intent_distribution=distribution,
        normalized_text="fenerbahçe bugün",
        token_count=2,
        has_verb_form=False,
    )

    assert label == "data.fixture_lookup"
    assert source == "telegraphic_inference"
    assert calibrated_prob == 0.65


def test_infer_telegraphic_intent_requires_temporal_entity() -> None:
    entities = [
        {"kind": "team", "confidence": 0.95, "source": "gazetteer"},
    ]

    assert infer_telegraphic_intent(
        entities=entities,
        intent_distribution=None,
        normalized_text="galatasaray",
        token_count=1,
        has_verb_form=False,
    ) is None
