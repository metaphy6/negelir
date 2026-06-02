"""Tests for Phase 10 §10.4 IntentClassifier scaffold.

Covers:
    1. Config keys exist with correct defaults (nlp_intent_model_path,
       nlp_intent_model_sha256, nlp_intent_model_max_size_mb).
    2. IntentModelNotFoundError raised when model file is absent.
    3. Size cap enforced (IntentModelTooLarge on > max_size_mb file).
    4. SHA256 mismatch raises IntentModelSHAMismatch before importing fasttext.
    5. Correct SHA skips the mismatch check; proceeds to fasttext import
       (expected to raise IntentModelUnavailable in the test env).
    6. Empty SHA disables verification; proceeds to fasttext import.
    7. Module exposes LATENCY_BUDGET_RTX_MS < LATENCY_BUDGET_AVX2_MS constants.
    8. MAX_MODEL_SIZE_MB constant == 20 (DoD).
    9. predict_intent() strips __label__ prefix and returns (str, float).
    10. Adversarial: model file with exactly max_size_mb is accepted.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal config stub
# ---------------------------------------------------------------------------


class _Cfg:
    def __init__(self, **kwargs):
        defaults = {
            "nlp_intent_model_path": "data/models/nlp/intent.tr.bin",
            "nlp_intent_model_sha256": "",
            "nlp_intent_model_max_size_mb": 20,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# §10.4 Config keys
# ---------------------------------------------------------------------------


class TestIntentModelConfig:
    def test_config_has_intent_model_path(self):
        from common.config import Config

        cfg = Config()
        assert hasattr(cfg, "nlp_intent_model_path")
        assert cfg.nlp_intent_model_path == "data/models/nlp/intent.tr.bin"

    def test_config_has_intent_model_sha256(self):
        from common.config import Config

        cfg = Config()
        assert hasattr(cfg, "nlp_intent_model_sha256")
        assert cfg.nlp_intent_model_sha256 == ""

    def test_config_has_intent_model_max_size_mb(self):
        from common.config import Config

        cfg = Config()
        assert hasattr(cfg, "nlp_intent_model_max_size_mb")
        assert cfg.nlp_intent_model_max_size_mb == 20

    def test_env_override_intent_model_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "NEGELIR_NLP_INTENT_MODEL_PATH", str(tmp_path / "my_intent.bin")
        )
        import importlib

        from common import config as _cm

        importlib.reload(_cm)
        try:
            cfg = _cm.Config()
            assert cfg.nlp_intent_model_path == str(tmp_path / "my_intent.bin")
        finally:
            importlib.reload(_cm)

    def test_env_override_canary_pod(self, monkeypatch):
        monkeypatch.setenv("NEGELIR_NLP_CANARY_POD", "1")
        import importlib

        from common import config as _cm

        importlib.reload(_cm)
        try:
            cfg = _cm.Config()
            assert cfg.nlp_canary_pod is True
        finally:
            importlib.reload(_cm)

    def test_env_override_shadow_mode(self, monkeypatch):
        monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
        import importlib

        from common import config as _cm

        importlib.reload(_cm)
        try:
            cfg = _cm.Config()
            assert cfg.nlp_intent_shadow_mode == "on"
        finally:
            importlib.reload(_cm)

    def test_config_validates_max_size_mb_bound(self):
        """nlp_intent_model_max_size_mb must be >= 1 (validator)."""
        import os

        os.environ["NEGELIR_NLP_INTENT_MODEL_MAX_SIZE_MB"] = "0"
        try:
            import importlib

            from common import config as _cm

            importlib.reload(_cm)
            cfg = _cm.Config()
            issues = cfg.validate(strict=False)
            assert any("nlp_intent_model_max_size_mb" in i for i in issues)
        finally:
            del os.environ["NEGELIR_NLP_INTENT_MODEL_MAX_SIZE_MB"]
            import importlib

            from common import config as _cm

            importlib.reload(_cm)

    def test_config_validates_shadow_mode(self):
        import os

        os.environ["NEGELIR_NLP_INTENT_SHADOW_MODE"] = "invalid"
        try:
            import importlib

            from common import config as _cm

            importlib.reload(_cm)
            cfg = _cm.Config()
            issues = cfg.validate(strict=False)
            assert any("nlp_intent_shadow_mode" in i for i in issues)
        finally:
            del os.environ["NEGELIR_NLP_INTENT_SHADOW_MODE"]
            import importlib

            from common import config as _cm

            importlib.reload(_cm)


# ---------------------------------------------------------------------------
# §10.4 IntentClassifier scaffold
# ---------------------------------------------------------------------------


class TestIntentClassifierScaffold:
    def test_model_not_found_raises(self, tmp_path):
        """IntentModelNotFoundError raised when model file is absent."""
        from nlp.intent import IntentClassifier, IntentModelNotFoundError

        cfg = _Cfg(nlp_intent_model_path=str(tmp_path / "missing.bin"))
        with pytest.raises(IntentModelNotFoundError, match="Intent model not found"):
            IntentClassifier.load(cfg)

    def test_size_cap_enforced(self, tmp_path):
        """IntentModelTooLarge raised when file exceeds size cap."""
        from nlp.intent import IntentClassifier, IntentModelTooLarge

        model_file = tmp_path / "big_intent.bin"
        model_file.write_bytes(b"\x00" * (21 * 1024 * 1024))
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_max_size_mb=20,
            nlp_intent_model_sha256="",
        )
        with pytest.raises(IntentModelTooLarge, match="exceeds size cap"):
            IntentClassifier.load(cfg)

    def test_exact_max_size_is_accepted(self, tmp_path):
        """A file that is exactly max_size_mb is accepted (boundary value)."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = tmp_path / "exact_intent.bin"
        model_file.write_bytes(b"x" * (20 * 1024 * 1024))
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_max_size_mb=20,
            nlp_intent_model_sha256="",
        )
        # Passes size check; fails only at fasttext import step.
        with pytest.raises(IntentModelUnavailable):
            IntentClassifier.load(cfg)

    def test_sha256_mismatch_raises(self, tmp_path):
        """IntentModelSHAMismatch raised when file SHA differs from pin."""
        from nlp.intent import IntentClassifier, IntentModelSHAMismatch

        model_file = tmp_path / "intent.bin"
        model_file.write_bytes(b"fake-model-bytes")
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_max_size_mb=20,
            nlp_intent_model_sha256="a" * 64,  # deliberately wrong
        )
        with pytest.raises(IntentModelSHAMismatch, match="SHA256 mismatch"):
            IntentClassifier.load(cfg)

    def test_sha256_mismatch_raised_before_fasttext(self, tmp_path):
        """SHA mismatch must be detected BEFORE the fasttext import attempt."""
        from nlp import intent as intent_mod
        from nlp.intent import IntentClassifier, IntentModelSHAMismatch

        model_file = tmp_path / "intent.bin"
        model_file.write_bytes(b"fake")
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256="b" * 64,
        )
        # Even if fasttext were somehow importable, SHA check runs first.
        with pytest.raises(IntentModelSHAMismatch):
            IntentClassifier.load(cfg)

    def test_sha256_empty_disables_verification(self, tmp_path):
        """Empty nlp_intent_model_sha256 skips the SHA check entirely."""
        from nlp.intent import IntentClassifier, IntentModelSHAMismatch, IntentModelUnavailable

        model_file = tmp_path / "intent.bin"
        model_file.write_bytes(b"fake-model-bytes")
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256="",
        )
        # Must NOT raise IntentModelSHAMismatch; reaches fasttext import.
        with pytest.raises(IntentModelUnavailable):
            IntentClassifier.load(cfg)

    def test_sha256_match_proceeds_to_fasttext(self, tmp_path):
        """Correct SHA passes verification; load proceeds to fasttext import."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = tmp_path / "intent.bin"
        content = b"fake-model-bytes-for-sha-check"
        model_file.write_bytes(content)
        actual_sha = hashlib.sha256(content).hexdigest()
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256=actual_sha,
            nlp_intent_model_max_size_mb=20,
        )
        with pytest.raises(IntentModelUnavailable, match="fasttext library"):
            IntentClassifier.load(cfg)

    def test_sidecar_sha_file_takes_precedence_over_config(self, tmp_path):
        """§10.21.1: Sidecar .sha256 file is checked before config."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = tmp_path / "intent.bin"
        content = b"fake-model-for-sidecar-test"
        model_file.write_bytes(content)
        actual_sha = hashlib.sha256(content).hexdigest()
        
        # Write correct SHA to sidecar
        sidecar_file = tmp_path / "intent.bin.sha256"
        sidecar_file.write_text(f"{actual_sha}  intent.bin\n", encoding="utf-8")
        
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256="wrong-sha-in-config" + ("0" * 50),  # deliberately wrong
            nlp_intent_model_max_size_mb=20,
        )
        # Sidecar is correct → passes, even though config SHA is wrong
        with pytest.raises(IntentModelUnavailable, match="fasttext library"):
            IntentClassifier.load(cfg)

    def test_sidecar_sha_mismatch_raises_with_alert_kind(self, tmp_path):
        """§10.21.1: Sidecar SHA mismatch → IntentModelSHAMismatch with alert kind."""
        from nlp.intent import IntentClassifier, IntentModelSHAMismatch

        model_file = tmp_path / "intent.bin"
        model_file.write_bytes(b"fake-model-bytes")
        
        # Write wrong SHA to sidecar
        sidecar_file = tmp_path / "intent.bin.sha256"
        sidecar_file.write_text("a" * 64 + "  intent.bin\n", encoding="utf-8")
        
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256="",  # empty config → only sidecar matters
            nlp_intent_model_max_size_mb=20,
        )
        with pytest.raises(
            IntentModelSHAMismatch,
            match=r"nlp_intent_model_sha_mismatch.*severity=critical"
        ):
            IntentClassifier.load(cfg)

    def test_canary_pod_loads_canary_model_path(self, tmp_path):
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = tmp_path / "intent.tr.bin"
        model_file.write_bytes(b"fake-model-bytes")
        canary_file = tmp_path / "intent.tr.bin.canary"
        canary_file.write_bytes(b"fake-canary-bytes")

        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_canary_pod=True,
            nlp_intent_model_sha256="",
        )

        resolved_path = IntentClassifier._resolve_model_path(cfg)
        assert resolved_path.name == "intent.tr.bin.canary"
        assert resolved_path.exists()

        with pytest.raises(IntentModelUnavailable, match="fasttext library"):
            IntentClassifier.load(cfg)

    def test_sidecar_sha_file_malformed_raises(self, tmp_path):
        """§10.21.1: Unreadable sidecar → IntentModelSHAMismatch."""
        from nlp.intent import IntentClassifier, IntentModelSHAMismatch

        model_file = tmp_path / "intent.bin"
        model_file.write_bytes(b"fake")
        
        # Write empty/malformed sidecar
        sidecar_file = tmp_path / "intent.bin.sha256"
        sidecar_file.write_text("", encoding="utf-8")
        
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256="",
            nlp_intent_model_max_size_mb=20,
        )
        with pytest.raises(IntentModelSHAMismatch, match="unreadable"):
            IntentClassifier.load(cfg)

    def test_sidecar_sha_missing_falls_back_to_config(self, tmp_path):
        """§10.21.1: No sidecar → fall back to config SHA."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = tmp_path / "intent.bin"
        content = b"fake-model-for-fallback"
        model_file.write_bytes(content)
        actual_sha = hashlib.sha256(content).hexdigest()
        
        # No sidecar file
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256=actual_sha,  # correct SHA in config
            nlp_intent_model_max_size_mb=20,
        )
        # Passes SHA check via config fallback
        with pytest.raises(IntentModelUnavailable, match="fasttext library"):
            IntentClassifier.load(cfg)

    def test_neither_sidecar_nor_config_skips_verification(self, tmp_path):
        """§10.21.1: No sidecar and empty config → skip SHA check (dev mode)."""
        from nlp.intent import IntentClassifier, IntentModelUnavailable

        model_file = tmp_path / "intent.bin"
        model_file.write_bytes(b"anything")
        
        # No sidecar, empty config
        cfg = _Cfg(
            nlp_intent_model_path=str(model_file),
            nlp_intent_model_sha256="",
            nlp_intent_model_max_size_mb=20,
        )
        # Skips SHA check; reaches fasttext import
        with pytest.raises(IntentModelUnavailable, match="fasttext library"):
            IntentClassifier.load(cfg)


# ---------------------------------------------------------------------------
# §10.4 Module-level constants
# ---------------------------------------------------------------------------


class TestIntentModuleConstants:
    def test_max_model_size_constant_is_20(self):
        import nlp.intent as intent_mod

        assert intent_mod.MAX_MODEL_SIZE_MB == 20

    def test_latency_budget_constants_exist_and_ordered(self):
        import nlp.intent as intent_mod

        assert hasattr(intent_mod, "LATENCY_BUDGET_RTX_MS")
        assert hasattr(intent_mod, "LATENCY_BUDGET_AVX2_MS")
        assert intent_mod.LATENCY_BUDGET_RTX_MS < intent_mod.LATENCY_BUDGET_AVX2_MS

    def test_latency_budget_rtx_under_1ms(self):
        import nlp.intent as intent_mod

        # LATENCY_BUDGET_RTX_MS is the upper bound; §10.4 says "<1 ms on RTX-4080m".
        assert intent_mod.LATENCY_BUDGET_RTX_MS <= 1.0

    def test_latency_budget_avx2_at_most_5ms(self):
        import nlp.intent as intent_mod

        assert intent_mod.LATENCY_BUDGET_AVX2_MS <= 5.0


# ---------------------------------------------------------------------------
# §10.4 predict_intent (via mock model)
# ---------------------------------------------------------------------------


class TestPredictIntent:
    def _make_clf(self, tmp_path):
        from nlp.intent import IntentClassifier

        mock_model = MagicMock()
        return IntentClassifier(_model=mock_model, model_path=tmp_path / "m.bin")

    def test_label_prefix_stripped(self, tmp_path):
        clf = self._make_clf(tmp_path)
        clf._model.predict.return_value = (
            ["__label__predict.match_outcome"],
            [0.92],
        )
        label, prob = clf.predict_intent("Galatasaray kazanir mi?")
        assert label == "predict.match_outcome"
        assert abs(prob - 0.92) < 1e-6

    def test_calls_fasttext_with_k1(self, tmp_path):
        clf = self._make_clf(tmp_path)
        clf._model.predict.return_value = (["__label__meta.help"], [0.60])
        clf.predict_intent("yardim")
        clf._model.predict.assert_called_once_with("yardim", k=1)

    def test_returns_float_probability(self, tmp_path):
        clf = self._make_clf(tmp_path)
        clf._model.predict.return_value = (["__label__data.standings"], [0.77])
        _, prob = clf.predict_intent("puan durumu")
        assert isinstance(prob, float)

    def test_adversarial_label_with_no_prefix(self, tmp_path):
        """Labels without __label__ prefix are returned unchanged."""
        clf = self._make_clf(tmp_path)
        clf._model.predict.return_value = (["meta.adversarial"], [0.99])
        label, _ = clf.predict_intent("some adversarial input")
        assert label == "meta.adversarial"
