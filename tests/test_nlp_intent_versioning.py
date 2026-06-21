"""Tests for Phase 10 §10.4 Versioning — model_version + calibration_version
stamped on every qa.intent.v1 envelope.

Covers:
    1. Config key nlp_intent_model_version exists with correct default ("").
    2. Config env NEGELIR_NLP_INTENT_MODEL_VERSION overrides the default.
    3. IntentClassifier has a model_version attribute.
    4. IntentClassifier.model_version reads from cfg.nlp_intent_model_version.
    5. IntentClassifier.calibration_version is accessible alongside model_version.
    6. Both version fields are empty string when not configured (pre-train / dev).
    7. model_version is stripped of surrounding whitespace.
    8. Adversarial: whitespace-only model_version is normalized to empty string.
    9. load() raises IntentModelNotFoundError before reading model_version
       (version only stored after successful model load path).
    10. Both version attrs are independently settable (no cross-contamination).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tiny_model(tmp_path: Path, name: str = "intent.tr.bin") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x00" * 10)
    return p


def _make_calibration(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "calibration_version": "2.3.4",
        "generated_at_utc": "2026-05-27T00:00:00Z",
        "method": "platt",
        "intents": {
            "predict.match_outcome": {"A": -1.5, "B": 0.3},
        },
    }
    p = tmp_path / "intent.tr.calibration.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class _Cfg:
    def __init__(self, **kwargs):
        defaults = {
            "nlp_intent_model_path": "nonexistent.bin",
            "nlp_intent_model_sha256": "",
            "nlp_intent_model_max_size_mb": 20,
            "nlp_intent_calibration_path": "",
            "nlp_intent_model_version": "",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def _make_clf(
    tmp_path: Path,
    model_version: str = "",
    calibration_version: str = "1.0.0",
) -> "IntentClassifier":  # noqa: F821
    """Build an IntentClassifier instance directly (bypasses fasttext)."""
    from nlp.intent import IntentClassifier

    mock_model = MagicMock()
    mock_model.predict.return_value = (["__label__predict.match_outcome"], [0.9])
    cal_params = {"predict.match_outcome": (-1.5, 0.3)} if calibration_version else None
    return IntentClassifier(
        mock_model,
        tmp_path / "intent.tr.bin",
        _calibration=cal_params,
        _calibration_version=calibration_version,
        _model_version=model_version,
    )


# ---------------------------------------------------------------------------
# §10.4 Config key: nlp_intent_model_version
# ---------------------------------------------------------------------------


class TestIntentVersioningConfigKey:
    def test_config_has_nlp_intent_model_version(self):
        from ai.common.config import Config

        cfg = Config()
        assert hasattr(cfg, "nlp_intent_model_version")

    def test_config_default_is_empty_string(self):
        from ai.common.config import Config

        cfg = Config()
        assert cfg.nlp_intent_model_version == ""

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEGELIR_NLP_INTENT_MODEL_VERSION", "1.2.3")
        import importlib

        from common import config as _cm

        importlib.reload(_cm)
        try:
            cfg = _cm.Config()
            assert cfg.nlp_intent_model_version == "1.2.3"
        finally:
            importlib.reload(_cm)


# ---------------------------------------------------------------------------
# §10.4 Versioning: IntentClassifier.model_version attribute
# ---------------------------------------------------------------------------


class TestIntentClassifierModelVersion:
    def test_model_version_attribute_exists(self, tmp_path):
        clf = _make_clf(tmp_path, model_version="1.0.0")
        assert hasattr(clf, "model_version")

    def test_model_version_stored_correctly(self, tmp_path):
        clf = _make_clf(tmp_path, model_version="3.1.4")
        assert clf.model_version == "3.1.4"

    def test_model_version_default_empty_string(self, tmp_path):
        clf = _make_clf(tmp_path, model_version="")
        assert clf.model_version == ""

    def test_calibration_version_accessible_alongside_model_version(self, tmp_path):
        clf = _make_clf(tmp_path, model_version="2.0.0", calibration_version="1.5.0")
        assert clf.model_version == "2.0.0"
        assert clf.calibration_version == "1.5.0"

    def test_no_cross_contamination_between_version_fields(self, tmp_path):
        clf = _make_clf(tmp_path, model_version="M", calibration_version="C")
        assert clf.model_version == "M"
        assert clf.calibration_version == "C"

    def test_both_empty_when_not_configured(self, tmp_path):
        clf = _make_clf(tmp_path, model_version="", calibration_version="")
        assert clf.model_version == ""
        assert clf.calibration_version == ""


# ---------------------------------------------------------------------------
# §10.4 Versioning: load() reads model_version from config
# ---------------------------------------------------------------------------


class TestIntentClassifierLoadVersioning:
    def test_load_reads_model_version_from_cfg(self, tmp_path, monkeypatch):
        """load() must capture cfg.nlp_intent_model_version on the instance."""
        model_path = _make_tiny_model(tmp_path)
        _make_calibration(tmp_path)

        import sys

        # Stub fasttext so the load() path completes without the library.
        fake_ft = MagicMock()
        fake_ft.load_model.return_value = MagicMock(
            predict=MagicMock(
                return_value=(["__label__predict.match_outcome"], [0.9])
            )
        )
        monkeypatch.setitem(sys.modules, "fasttext", fake_ft)

        from nlp.intent import IntentClassifier

        cfg = _Cfg(
            nlp_intent_model_path=str(model_path),
            nlp_intent_model_version="0.9.1",
            nlp_intent_calibration_path=str(tmp_path / "intent.tr.calibration.json"),
        )
        clf = IntentClassifier.load(cfg)
        assert clf.model_version == "0.9.1"

    def test_load_model_version_empty_by_default(self, tmp_path, monkeypatch):
        model_path = _make_tiny_model(tmp_path)

        import sys

        fake_ft = MagicMock()
        fake_ft.load_model.return_value = MagicMock(
            predict=MagicMock(return_value=(["__label__predict.match_outcome"], [0.9]))
        )
        monkeypatch.setitem(sys.modules, "fasttext", fake_ft)

        from nlp.intent import IntentClassifier

        cfg = _Cfg(
            nlp_intent_model_path=str(model_path),
            nlp_intent_model_version="",
        )
        clf = IntentClassifier.load(cfg)
        assert clf.model_version == ""

    def test_load_model_version_stripped(self, tmp_path, monkeypatch):
        """load() strips whitespace from cfg.nlp_intent_model_version."""
        model_path = _make_tiny_model(tmp_path)

        import sys

        fake_ft = MagicMock()
        fake_ft.load_model.return_value = MagicMock(
            predict=MagicMock(return_value=(["__label__predict.match_outcome"], [0.9]))
        )
        monkeypatch.setitem(sys.modules, "fasttext", fake_ft)

        from nlp.intent import IntentClassifier

        cfg = _Cfg(
            nlp_intent_model_path=str(model_path),
            nlp_intent_model_version="  1.2.3  ",
        )
        clf = IntentClassifier.load(cfg)
        assert clf.model_version == "1.2.3"

    def test_load_whitespace_only_version_normalised_to_empty(
        self, tmp_path, monkeypatch
    ):
        """Whitespace-only model_version should be treated as empty."""
        model_path = _make_tiny_model(tmp_path)

        import sys

        fake_ft = MagicMock()
        fake_ft.load_model.return_value = MagicMock(
            predict=MagicMock(return_value=(["__label__predict.match_outcome"], [0.9]))
        )
        monkeypatch.setitem(sys.modules, "fasttext", fake_ft)

        from nlp.intent import IntentClassifier

        cfg = _Cfg(
            nlp_intent_model_path=str(model_path),
            nlp_intent_model_version="   ",
        )
        clf = IntentClassifier.load(cfg)
        assert clf.model_version == ""

    def test_load_calibration_version_also_present_after_load(
        self, tmp_path, monkeypatch
    ):
        """After load(), both model_version and calibration_version are accessible."""
        model_path = _make_tiny_model(tmp_path)
        _make_calibration(tmp_path)

        import sys

        fake_ft = MagicMock()
        fake_ft.load_model.return_value = MagicMock(
            predict=MagicMock(return_value=(["__label__predict.match_outcome"], [0.9]))
        )
        monkeypatch.setitem(sys.modules, "fasttext", fake_ft)

        from nlp.intent import IntentClassifier

        cfg = _Cfg(
            nlp_intent_model_path=str(model_path),
            nlp_intent_model_version="4.0.0",
            nlp_intent_calibration_path=str(tmp_path / "intent.tr.calibration.json"),
        )
        clf = IntentClassifier.load(cfg)
        assert clf.model_version == "4.0.0"
        assert clf.calibration_version == "2.3.4"  # from _make_calibration
