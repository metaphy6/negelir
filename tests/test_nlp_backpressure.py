"""Phase 10 §10.19 — backpressure config tests.

When qa.intent.v1 queue depth exceeds cfg.nlp_queue_pressure_threshold=100:
(a) disable humanizer (template-only mode) for cfg.nlp_pressure_humanize_off_s=60;
(b) widen nlp_intent_cache_ttl_s 2x;
(c) emit nlp.alert.v1{kind=nlp_queue_pressure, severity=warn} (debounced 60s).

This test verifies the config keys exist and the stub backpressure check logic.
Full backpressure implementation (humanizer disable, cache widening, alert
emission) lands in subsequent §10.19 bullets.
"""
from common.config import cfg
from swarm.agents.nlp import NlpDispatcherAgent


def test_backpressure_config_keys_exist():
    """§10.19 triangle test: config keys exist in config.py."""
    assert hasattr(cfg, "nlp_queue_pressure_threshold")
    assert hasattr(cfg, "nlp_pressure_humanize_off_s")
    assert cfg.nlp_queue_pressure_threshold == 100
    assert cfg.nlp_pressure_humanize_off_s == 60


def test_backpressure_stub_threshold_logic():
    """§10.19 stub: _check_backpressure returns True when queue_depth > threshold."""
    agent = NlpDispatcherAgent()
    
    # Below threshold → no pressure
    assert agent._check_backpressure(50) is False
    assert agent._check_backpressure(100) is False
    
    # Above threshold → pressure active
    assert agent._check_backpressure(101) is True
    assert agent._check_backpressure(200) is True


def test_backpressure_stub_respects_config():
    """§10.19 stub: _check_backpressure reads cfg.nlp_queue_pressure_threshold."""
    agent = NlpDispatcherAgent()
    
    # Default threshold is 100
    threshold = cfg.nlp_queue_pressure_threshold
    assert agent._check_backpressure(threshold) is False
    assert agent._check_backpressure(threshold + 1) is True
