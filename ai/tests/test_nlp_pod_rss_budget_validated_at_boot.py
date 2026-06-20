"""Phase 10 §10.21.2 — RSS ceiling per pod boot validator test.

Validates that the boot-time validator sums all NLP sub-component RSS budgets
and refuses start when they exceed the pod-level cap.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.common.config import Config


def test_nlp_pod_rss_budget_validated_at_boot_within_cap():
    """§10.21.2 proof (a): when sum of sub-knobs <= cap, validate passes."""
    # Create a config with sub-knobs that sum to within the cap.
    cfg = Config()
    cfg.nlp_lexicon_max_rss_mb = 128
    cfg.nlp_intent_model_max_size_mb = 20
    cfg.nlp_crf_max_rss_mb = 5
    cfg.nlp_symspell_max_rss_mb = 100
    cfg.nlp_jinja_cache_max_rss_mb = 50
    cfg.nlp_python_overhead_mb = 200
    cfg.nlp_humanizer_max_rss_mb = 1024
    cfg.nlp_pod_rss_max_mb = 2048  # sum = 1527, well within cap

    issues = cfg.validate()
    # Filter to only RSS-related issues
    rss_issues = [i for i in issues if "nlp_pod_rss_max_mb" in i]
    assert len(rss_issues) == 0, (
        f"Expected no RSS budget issues when sum <= cap, got: {rss_issues}"
    )


def test_nlp_pod_rss_budget_validated_at_boot_exceeds_cap():
    """§10.21.2 proof (b): when sum of sub-knobs > cap, validate refuses."""
    # Create a config where sub-knobs sum exceeds the cap.
    cfg = Config()
    cfg.nlp_lexicon_max_rss_mb = 300  # Overtuned
    cfg.nlp_intent_model_max_size_mb = 50
    cfg.nlp_crf_max_rss_mb = 10
    cfg.nlp_symspell_max_rss_mb = 200
    cfg.nlp_jinja_cache_max_rss_mb = 100
    cfg.nlp_python_overhead_mb = 400
    cfg.nlp_humanizer_max_rss_mb = 2048  # Overtuned
    cfg.nlp_pod_rss_max_mb = 2048  # sum = 3108, exceeds cap

    issues = cfg.validate()
    # Filter to only RSS-related issues
    rss_issues = [i for i in issues if "nlp_pod_rss_max_mb" in i]
    assert len(rss_issues) == 1, (
        f"Expected exactly 1 RSS budget issue when sum > cap, got {len(rss_issues)}: {rss_issues}"
    )
    assert "exceeded by sum of sub-knobs" in rss_issues[0]
    assert "3108 MB" in rss_issues[0]


def test_nlp_pod_rss_budget_validated_at_boot_default_values():
    """§10.21.2 proof (c): default values in .env.example sum to within cap."""
    # The defaults specified in the bullet description:
    # lexicons 128 + intent 20 + crf 5 + jinja 50 + symspell 100
    # + python 200 + humanizer 1024 + headroom = 1527 MB
    # Cap default = 2048 MB. This should pass.
    cfg = Config()
    # Use default values from config.py field definitions
    # These should match the .env.example values

    issues = cfg.validate()
    rss_issues = [i for i in issues if "nlp_pod_rss_max_mb" in i]
    assert len(rss_issues) == 0, (
        f"Default config values should sum to within cap. Got issues: {rss_issues}"
    )


def test_nlp_pod_rss_budget_validated_at_boot_strict_mode():
    """§10.21.2 proof (d): strict mode raises ValueError on budget overflow."""
    cfg = Config()
    cfg.nlp_lexicon_max_rss_mb = 500  # Overtuned
    cfg.nlp_intent_model_max_size_mb = 50
    cfg.nlp_crf_max_rss_mb = 10
    cfg.nlp_symspell_max_rss_mb = 200
    cfg.nlp_jinja_cache_max_rss_mb = 100
    cfg.nlp_python_overhead_mb = 400
    cfg.nlp_humanizer_max_rss_mb = 2048  # Overtuned
    cfg.nlp_pod_rss_max_mb = 2048  # sum = 3308, exceeds cap

    with pytest.raises(ValueError) as exc_info:
        cfg.validate(strict=True)
    
    assert "nlp_pod_rss_max_mb" in str(exc_info.value)
    assert "exceeded by sum of sub-knobs" in str(exc_info.value)


def test_nlp_pod_rss_budget_validated_at_boot_exact_cap():
    """§10.21.2 proof (e): sum exactly equal to cap passes validation."""
    cfg = Config()
    cfg.nlp_lexicon_max_rss_mb = 128
    cfg.nlp_intent_model_max_size_mb = 20
    cfg.nlp_crf_max_rss_mb = 5
    cfg.nlp_symspell_max_rss_mb = 100
    cfg.nlp_jinja_cache_max_rss_mb = 50
    cfg.nlp_python_overhead_mb = 400
    cfg.nlp_humanizer_max_rss_mb = 1345  # Adjusted to hit exactly 2048
    cfg.nlp_pod_rss_max_mb = 2048  # sum = 2048 exactly

    issues = cfg.validate()
    rss_issues = [i for i in issues if "nlp_pod_rss_max_mb" in i]
    assert len(rss_issues) == 0, (
        f"Sum exactly equal to cap should pass. Got issues: {rss_issues}"
    )


def test_nlp_pod_rss_budget_validated_at_boot_off_by_one():
    """§10.21.2 proof (f): sum exceeding cap by 1 MB is caught."""
    cfg = Config()
    cfg.nlp_lexicon_max_rss_mb = 128
    cfg.nlp_intent_model_max_size_mb = 20
    cfg.nlp_crf_max_rss_mb = 5
    cfg.nlp_symspell_max_rss_mb = 100
    cfg.nlp_jinja_cache_max_rss_mb = 50
    cfg.nlp_python_overhead_mb = 400
    cfg.nlp_humanizer_max_rss_mb = 1346  # Adjusted to exceed by 1 MB
    cfg.nlp_pod_rss_max_mb = 2048  # sum = 2049, exceeds by 1

    issues = cfg.validate()
    rss_issues = [i for i in issues if "nlp_pod_rss_max_mb" in i]
    assert len(rss_issues) == 1, (
        f"Sum exceeding cap by 1 MB should fail. Got {len(rss_issues)} issues: {rss_issues}"
    )
    assert "2049 MB" in rss_issues[0]
