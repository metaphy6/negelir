"""Phase 10 §10.32 — NLP flame capture config tests.

This test verifies the new operator flame capture knobs exist in Config,
have the expected default values, and are env-overridable.
"""

import importlib

import pytest


def test_flame_capture_config_keys_exist():
    from common.config import Config

    cfg = Config()
    assert hasattr(cfg, "opsctl_flame_capture_ttl_h")
    assert hasattr(cfg, "opsctl_flame_capture_max_armed_per_h")
    assert hasattr(cfg, "nlp_flame_capture_overhead_floor_pct")
    assert cfg.opsctl_flame_capture_ttl_h == 24
    assert cfg.opsctl_flame_capture_max_armed_per_h == 10
    assert cfg.nlp_flame_capture_overhead_floor_pct == pytest.approx(5.0)


def test_flame_capture_env_override(monkeypatch):
    monkeypatch.setenv("NEGELIR_OPSCTL_FLAME_CAPTURE_TTL_H", "48")
    monkeypatch.setenv("NEGELIR_OPSCTL_FLAME_CAPTURE_MAX_ARMED_PER_H", "20")
    monkeypatch.setenv("NEGELIR_NLP_FLAME_CAPTURE_OVERHEAD_FLOOR_PCT", "7.5")

    import common.config as _cm
    importlib.reload(_cm)
    try:
        cfg = _cm.Config()
        assert cfg.opsctl_flame_capture_ttl_h == 48
        assert cfg.opsctl_flame_capture_max_armed_per_h == 20
        assert cfg.nlp_flame_capture_overhead_floor_pct == pytest.approx(7.5)
    finally:
        importlib.reload(_cm)
