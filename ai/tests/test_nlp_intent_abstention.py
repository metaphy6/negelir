"""Tests for Phase 10 §10.4 Abstention threshold.

Covers:
    1. Config key nlp_min_intent_conf exists with default 0.55.
    2. Config key is env-overridable via NEGELIR_NLP_MIN_INTENT_CONF.
    3. IntentAbstention is a NamedTuple with (suggestions, top_conf).
    4. classify() returns IntentScore when calibrated_prob >= min_conf.
    5. classify() returns IntentAbstention when calibrated_prob < min_conf.
    6. IntentAbstention.suggestions carries the top-k IntentScore list.
    7. IntentAbstention.top_conf equals the top-1 calibrated_prob.
    8. classify() with min_conf=0.0 never abstains (always returns IntentScore).
    9. classify() with min_conf=1.0 always abstains (no real probability == 1.0).
   10. classify() with empty scores returns IntentAbstention(suggestions=[], top_conf=0.0).
   11. Adversarial: min_conf exactly equals top calibrated_prob — should NOT abstain.
   12. Adversarial: very small calibrated_prob (near 0) triggers abstention.
"""
from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_clf(tmp_path: Path, calibration=None, cal_version=""):
    from nlp.intent import IntentClassifier

    mock_model = MagicMock()
    return IntentClassifier(
        _model=mock_model,
        model_path=tmp_path / "intent.tr.bin",
        _calibration=calibration,
        _calibration_version=cal_version,
    )


def _patch_distribution(clf, scores):
    """Monkeypatch predict_intent_distribution to return *scores*."""
    from nlp import intent as _intent_mod
    from nlp.intent import IntentScore

    entries = [
        IntentScore(label=label, raw_prob=rp, calibrated_prob=cp)
        for label, rp, cp in scores
    ]
    clf.predict_intent_distribution = MagicMock(return_value=entries)
    return clf


# ---------------------------------------------------------------------------
# 1. Config key nlp_min_intent_conf
# ---------------------------------------------------------------------------


class TestMinIntentConfConfig:
    def test_config_has_min_intent_conf(self):
        from common.config import Config

        cfg = Config()
        assert hasattr(cfg, "nlp_min_intent_conf")

    def test_default_is_0_55(self):
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_min_intent_conf == pytest.approx(0.55)

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEGELIR_NLP_MIN_INTENT_CONF", "0.70")
        import importlib

        from common import config as _cm

        importlib.reload(_cm)
        try:
            cfg = _cm.Config()
            assert cfg.nlp_min_intent_conf == pytest.approx(0.70)
        finally:
            importlib.reload(_cm)


# ---------------------------------------------------------------------------
# 2. IntentAbstention structure
# ---------------------------------------------------------------------------


class TestIntentAbstentionType:
    def test_is_named_tuple(self):
        from nlp.intent import IntentAbstention

        ab = IntentAbstention(suggestions=[], top_conf=0.3)
        assert isinstance(ab, tuple)
        assert ab.suggestions == []
        assert ab.top_conf == pytest.approx(0.3)

    def test_fields(self):
        from nlp.intent import IntentAbstention

        assert IntentAbstention._fields == ("suggestions", "top_conf")


# ---------------------------------------------------------------------------
# 3. classify() happy path — returns IntentScore when above threshold
# ---------------------------------------------------------------------------


class TestClassifyAboveThreshold:
    def test_returns_intent_score_when_above(self, tmp_path):
        from nlp.intent import IntentScore

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [
                ("predict.match_outcome", 0.8, 0.80),
                ("predict.btts", 0.1, 0.10),
                ("data.standings", 0.05, 0.05),
            ],
        )
        result = clf.classify("Galatasaray maçı tahmini", min_conf=0.55)
        assert isinstance(result, IntentScore)
        assert result.label == "predict.match_outcome"
        assert result.calibrated_prob == pytest.approx(0.80)

    def test_min_conf_zero_never_abstains(self, tmp_path):
        from nlp.intent import IntentScore

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [("predict.match_outcome", 0.01, 0.01)],
        )
        result = clf.classify("test", min_conf=0.0)
        assert isinstance(result, IntentScore)

    def test_exactly_at_threshold_does_not_abstain(self, tmp_path):
        """Exactly at min_conf should NOT abstain (>= comparison)."""
        from nlp.intent import IntentScore

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [("predict.match_outcome", 0.55, 0.55)],
        )
        result = clf.classify("test", min_conf=0.55)
        assert isinstance(result, IntentScore)
        assert result.calibrated_prob == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# 4. classify() abstention path — returns IntentAbstention when below threshold
# ---------------------------------------------------------------------------


class TestClassifyBelowThreshold:
    def test_returns_abstention_when_below(self, tmp_path):
        from nlp.intent import IntentAbstention

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [
                ("predict.match_outcome", 0.4, 0.40),
                ("predict.btts", 0.3, 0.30),
                ("data.standings", 0.2, 0.20),
            ],
        )
        result = clf.classify("belirsiz metin", min_conf=0.55)
        assert isinstance(result, IntentAbstention)

    def test_abstention_top_conf_equals_top_calibrated(self, tmp_path):
        from nlp.intent import IntentAbstention

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [
                ("predict.match_outcome", 0.4, 0.40),
                ("predict.btts", 0.3, 0.30),
            ],
        )
        result = clf.classify("test", min_conf=0.55)
        assert isinstance(result, IntentAbstention)
        assert result.top_conf == pytest.approx(0.40)

    def test_abstention_suggestions_carries_top_k(self, tmp_path):
        from nlp.intent import IntentAbstention, IntentScore

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [
                ("predict.match_outcome", 0.4, 0.40),
                ("predict.btts", 0.3, 0.30),
                ("data.standings", 0.2, 0.20),
            ],
        )
        result = clf.classify("test", min_conf=0.55)
        assert isinstance(result, IntentAbstention)
        assert len(result.suggestions) == 3
        assert all(isinstance(s, IntentScore) for s in result.suggestions)
        assert result.suggestions[0].label == "predict.match_outcome"

    def test_min_conf_one_always_abstains(self, tmp_path):
        from nlp.intent import IntentAbstention

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [("predict.match_outcome", 0.99, 0.99)],
        )
        result = clf.classify("test", min_conf=1.0)
        assert isinstance(result, IntentAbstention)

    def test_very_low_prob_triggers_abstention(self, tmp_path):
        from nlp.intent import IntentAbstention

        clf = _make_clf(tmp_path)
        clf = _patch_distribution(
            clf,
            [("predict.match_outcome", 0.001, 0.001)],
        )
        result = clf.classify("test", min_conf=0.55)
        assert isinstance(result, IntentAbstention)
        assert result.top_conf == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# 5. Edge case: empty distribution → IntentAbstention with empty suggestions
# ---------------------------------------------------------------------------


class TestClassifyEmptyDistribution:
    def test_empty_scores_returns_abstention(self, tmp_path):
        from nlp.intent import IntentAbstention

        clf = _make_clf(tmp_path)
        clf.predict_intent_distribution = MagicMock(return_value=[])
        result = clf.classify("test", min_conf=0.55)
        assert isinstance(result, IntentAbstention)
        assert result.suggestions == []
        assert result.top_conf == pytest.approx(0.0)
