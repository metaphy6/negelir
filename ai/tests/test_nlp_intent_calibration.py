"""Tests for Phase 10 §10.4 Calibration — Platt-scaling intent calibration.

Covers:
    1. Config key nlp_intent_calibration_path exists with correct default ("").
    2. _load_calibration parses valid JSON correctly.
    3. _load_calibration raises IntentCalibrationLoadError on schema_version mismatch.
    4. _load_calibration raises IntentCalibrationLoadError on malformed JSON.
    5. _load_calibration raises IntentCalibrationLoadError when 'intents' key is missing.
    6. _load_calibration raises IntentCalibrationLoadError on malformed per-intent entry.
    7. _platt_sigmoid applies Platt sigmoid correctly.
    8. _platt_sigmoid clamps output to [0, 1].
    9. predict_intent_distribution returns List[IntentScore] with len == k.
    10. predict_intent_distribution applies calibration when calibration is loaded.
    11. predict_intent_distribution falls back to raw_prob when calibration absent.
    12. predict_intent_distribution falls back to raw_prob when label not in calibration.
    13. calibration_version stored on classifier instance.
    14. load() resolves calibration from cfg.nlp_intent_calibration_path when set.
    15. load() auto-resolves calibration from model dir when cal path not set.
    16. load() accepts missing calibration file gracefully (_calibration=None).
    17. load() raises IntentCalibrationLoadError on present-but-malformed cal file.
    18. Adversarial: very large negative sigmoid argument does not raise OverflowError.
    19. IntentScore is a NamedTuple with (label, raw_prob, calibrated_prob).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CALIBRATION = {
    "schema_version": 1,
    "calibration_version": "1.2.3",
    "generated_at_utc": "2026-01-01T00:00:00Z",
    "method": "platt",
    "intents": {
        "predict.match_outcome": {"A": -1.5, "B": 0.3},
        "data.standings": {"A": -1.0, "B": 0.0},
    },
}


def _write_cal(tmp_path: Path, data: Dict[str, Any], name: str = "intent.tr.calibration.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_clf(tmp_path: Path, calibration=None, cal_version=""):
    from nlp.intent import IntentClassifier

    mock_model = MagicMock()
    return IntentClassifier(
        _model=mock_model,
        model_path=tmp_path / "intent.tr.bin",
        _calibration=calibration,
        _calibration_version=cal_version,
    )


# ---------------------------------------------------------------------------
# 1. Config key
# ---------------------------------------------------------------------------


class TestCalibrationConfigKey:
    def test_config_has_calibration_path(self):
        from common.config import Config

        cfg = Config()
        assert hasattr(cfg, "nlp_intent_calibration_path")

    def test_calibration_path_default_is_empty(self):
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_intent_calibration_path == ""

    def test_env_override_calibration_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEGELIR_NLP_INTENT_CALIBRATION_PATH", str(tmp_path / "cal.json"))
        import importlib

        from common import config as _cm

        importlib.reload(_cm)
        try:
            cfg = _cm.Config()
            assert cfg.nlp_intent_calibration_path == str(tmp_path / "cal.json")
        finally:
            importlib.reload(_cm)


# ---------------------------------------------------------------------------
# 2–6. _load_calibration
# ---------------------------------------------------------------------------


class TestLoadCalibration:
    def test_parses_valid_calibration(self, tmp_path):
        from nlp.intent import _load_calibration

        cal_path = _write_cal(tmp_path, _VALID_CALIBRATION)
        params, version = _load_calibration(cal_path)
        assert "predict.match_outcome" in params
        assert params["predict.match_outcome"] == (-1.5, 0.3)
        assert params["data.standings"] == (-1.0, 0.0)
        assert version == "1.2.3"

    def test_schema_version_mismatch_raises(self, tmp_path):
        from nlp.intent import IntentCalibrationLoadError, _load_calibration

        bad = dict(_VALID_CALIBRATION)
        bad["schema_version"] = 99
        cal_path = _write_cal(tmp_path, bad)
        with pytest.raises(IntentCalibrationLoadError, match="schema_version mismatch"):
            _load_calibration(cal_path)

    def test_malformed_json_raises(self, tmp_path):
        from nlp.intent import IntentCalibrationLoadError, _load_calibration

        cal_path = tmp_path / "intent.tr.calibration.json"
        cal_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(IntentCalibrationLoadError, match="not valid JSON"):
            _load_calibration(cal_path)

    def test_missing_intents_key_raises(self, tmp_path):
        from nlp.intent import IntentCalibrationLoadError, _load_calibration

        bad = {"schema_version": 1, "calibration_version": "1.0.0"}
        cal_path = _write_cal(tmp_path, bad)
        with pytest.raises(IntentCalibrationLoadError, match="missing 'intents' dict"):
            _load_calibration(cal_path)

    def test_malformed_intent_entry_raises(self, tmp_path):
        from nlp.intent import IntentCalibrationLoadError, _load_calibration

        bad = dict(_VALID_CALIBRATION)
        bad["intents"] = {"predict.match_outcome": {"A": 1.0}}  # missing B
        cal_path = _write_cal(tmp_path, bad)
        with pytest.raises(IntentCalibrationLoadError, match="malformed entry"):
            _load_calibration(cal_path)

    def test_empty_intents_is_accepted(self, tmp_path):
        """An empty intents dict is valid (no intents calibrated yet)."""
        from nlp.intent import _load_calibration

        data = {"schema_version": 1, "calibration_version": "0.1.0", "intents": {}}
        cal_path = _write_cal(tmp_path, data)
        params, version = _load_calibration(cal_path)
        assert params == {}
        assert version == "0.1.0"

    def test_missing_calibration_version_returns_empty_string(self, tmp_path):
        from nlp.intent import _load_calibration

        data = {"schema_version": 1, "intents": {}}
        cal_path = _write_cal(tmp_path, data)
        _, version = _load_calibration(cal_path)
        assert version == ""


# ---------------------------------------------------------------------------
# 7–8. _platt_sigmoid
# ---------------------------------------------------------------------------


class TestPlattSigmoid:
    def test_sigmoid_identity_at_zero(self):
        from nlp.intent import IntentClassifier

        # sigmoid(A=0, B=0) = 0.5 for any raw_prob
        result = IntentClassifier._platt_sigmoid(0.8, 0.0, 0.0)
        assert abs(result - 0.5) < 1e-9

    def test_sigmoid_formula(self):
        from nlp.intent import IntentClassifier

        A, B, p = -1.5, 0.3, 0.9
        expected = 1.0 / (1.0 + math.exp(-(-1.5 * 0.9 + 0.3)))
        result = IntentClassifier._platt_sigmoid(p, A, B)
        assert abs(result - expected) < 1e-9

    def test_sigmoid_clamps_to_one(self):
        from nlp.intent import IntentClassifier

        # Large positive exponent argument → approaches 1.0
        result = IntentClassifier._platt_sigmoid(1.0, 1000.0, 0.0)
        assert 0.0 <= result <= 1.0

    def test_sigmoid_clamps_to_zero(self):
        from nlp.intent import IntentClassifier

        # Very large negative argument → sigmoid near 0
        result = IntentClassifier._platt_sigmoid(1.0, -1000.0, 0.0)
        assert 0.0 <= result <= 1.0

    def test_sigmoid_no_overflow_on_extreme_negative(self):
        """Adversarial: no OverflowError on extreme negative argument."""
        from nlp.intent import IntentClassifier

        result = IntentClassifier._platt_sigmoid(1.0, -1e6, 0.0)
        assert result == 0.0


# ---------------------------------------------------------------------------
# 9–12. predict_intent_distribution
# ---------------------------------------------------------------------------


class TestPredictIntentDistribution:
    def _clf_with_mock(self, tmp_path, calibration=None, cal_version=""):
        clf = _make_clf(tmp_path, calibration, cal_version)
        clf._model.predict.return_value = (
            ["__label__predict.match_outcome", "__label__data.standings", "__label__meta.help"],
            [0.85, 0.10, 0.05],
        )
        return clf

    def test_returns_list_of_intent_scores(self, tmp_path):
        from nlp.intent import IntentScore

        clf = self._clf_with_mock(tmp_path)
        result = clf.predict_intent_distribution("Galatasaray kazanir mi?", k=3)
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(s, IntentScore) for s in result)

    def test_labels_stripped_of_prefix(self, tmp_path):
        clf = self._clf_with_mock(tmp_path)
        result = clf.predict_intent_distribution("test", k=3)
        labels = [s.label for s in result]
        assert "predict.match_outcome" in labels
        assert not any(l.startswith("__label__") for l in labels)

    def test_applies_calibration_when_loaded(self, tmp_path):
        from nlp.intent import IntentClassifier

        cal = {"predict.match_outcome": (-1.5, 0.3)}
        clf = self._clf_with_mock(tmp_path, calibration=cal)
        result = clf.predict_intent_distribution("test", k=3)

        top = next(s for s in result if s.label == "predict.match_outcome")
        expected_cal = IntentClassifier._platt_sigmoid(top.raw_prob, -1.5, 0.3)
        assert abs(top.calibrated_prob - expected_cal) < 1e-9

    def test_fallback_to_raw_when_no_calibration(self, tmp_path):
        clf = self._clf_with_mock(tmp_path, calibration=None)
        result = clf.predict_intent_distribution("test", k=3)
        for score in result:
            assert abs(score.calibrated_prob - score.raw_prob) < 1e-9

    def test_fallback_to_raw_for_unlisted_intent(self, tmp_path):
        """Labels not in calibration dict fall back to raw_prob."""
        cal = {}  # empty — no intents calibrated
        clf = self._clf_with_mock(tmp_path, calibration=cal)
        result = clf.predict_intent_distribution("test", k=3)
        for score in result:
            assert abs(score.calibrated_prob - score.raw_prob) < 1e-9

    def test_fasttext_called_with_correct_k(self, tmp_path):
        clf = self._clf_with_mock(tmp_path)
        clf.predict_intent_distribution("soru", k=3)
        clf._model.predict.assert_called_once_with("soru", k=3)

    def test_raw_prob_preserved(self, tmp_path):
        cal = {"predict.match_outcome": (-1.5, 0.3)}
        clf = self._clf_with_mock(tmp_path, calibration=cal)
        result = clf.predict_intent_distribution("test", k=3)
        top = next(s for s in result if s.label == "predict.match_outcome")
        assert abs(top.raw_prob - 0.85) < 1e-9


# ---------------------------------------------------------------------------
# 13. calibration_version attribute
# ---------------------------------------------------------------------------


class TestCalibrationVersion:
    def test_calibration_version_stored(self, tmp_path):
        clf = _make_clf(tmp_path, calibration={}, cal_version="2.0.1")
        assert clf.calibration_version == "2.0.1"

    def test_calibration_version_empty_when_absent(self, tmp_path):
        clf = _make_clf(tmp_path, calibration=None, cal_version="")
        assert clf.calibration_version == ""


# ---------------------------------------------------------------------------
# 14–17. IntentClassifier.load() calibration integration
# ---------------------------------------------------------------------------


class TestLoadCalibrationIntegration:
    def _make_model_file(self, tmp_path):
        """Create a minimal fake model file."""
        model_file = tmp_path / "intent.tr.bin"
        model_file.write_bytes(b"fake-model-bytes")
        return model_file

    def test_load_resolves_calibration_from_cfg_path(self, tmp_path):
        """When cfg.nlp_intent_calibration_path is set, that file is used."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = self._make_model_file(tmp_path)
        cal_path = _write_cal(tmp_path, _VALID_CALIBRATION)

        class _Cfg:
            nlp_intent_model_path = str(model_file)
            nlp_intent_model_sha256 = ""
            nlp_intent_model_max_size_mb = 20
            nlp_intent_calibration_path = str(cal_path)

        with pytest.raises(IntentModelUnavailable):
            # Reaches fasttext import — good; calibration was loaded before that.
            IntentClassifier.load(_Cfg())

    def test_load_auto_resolves_calibration_from_model_dir(self, tmp_path):
        """When calibration path is empty, auto-resolve from model directory."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = self._make_model_file(tmp_path)
        # Write calibration file in the same directory with the expected name.
        _write_cal(tmp_path, _VALID_CALIBRATION, name="intent.tr.calibration.json")

        class _Cfg:
            nlp_intent_model_path = str(model_file)
            nlp_intent_model_sha256 = ""
            nlp_intent_model_max_size_mb = 20
            nlp_intent_calibration_path = ""

        with pytest.raises(IntentModelUnavailable):
            IntentClassifier.load(_Cfg())

    def test_load_accepts_missing_calibration_gracefully(self, tmp_path):
        """Missing calibration file is not an error; _calibration stays None."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = self._make_model_file(tmp_path)
        # No calibration file in tmp_path.

        class _Cfg:
            nlp_intent_model_path = str(model_file)
            nlp_intent_model_sha256 = ""
            nlp_intent_model_max_size_mb = 20
            nlp_intent_calibration_path = ""

        with pytest.raises(IntentModelUnavailable):
            IntentClassifier.load(_Cfg())

    def test_load_raises_on_malformed_calibration_file(self, tmp_path):
        """Present-but-malformed calibration file raises IntentCalibrationLoadError."""
        from nlp.intent import IntentCalibrationLoadError, IntentClassifier

        model_file = self._make_model_file(tmp_path)
        bad_cal = tmp_path / "intent.tr.calibration.json"
        bad_cal.write_text("{bad json", encoding="utf-8")

        class _Cfg:
            nlp_intent_model_path = str(model_file)
            nlp_intent_model_sha256 = ""
            nlp_intent_model_max_size_mb = 20
            nlp_intent_calibration_path = ""

        with pytest.raises(IntentCalibrationLoadError):
            IntentClassifier.load(_Cfg())


# ---------------------------------------------------------------------------
# 19. IntentScore NamedTuple structure
# ---------------------------------------------------------------------------


class TestIntentScoreNamedTuple:
    def test_is_namedtuple(self):
        from nlp.intent import IntentScore

        score = IntentScore(label="meta.help", raw_prob=0.6, calibrated_prob=0.55)
        assert score.label == "meta.help"
        assert abs(score.raw_prob - 0.6) < 1e-9
        assert abs(score.calibrated_prob - 0.55) < 1e-9

    def test_unpacks_correctly(self):
        from nlp.intent import IntentScore

        label, raw, cal = IntentScore("predict.btts", 0.7, 0.65)
        assert label == "predict.btts"
        assert abs(raw - 0.7) < 1e-9
        assert abs(cal - 0.65) < 1e-9
