"""Phase 10 §10.19 — Test for NLP answer audit sampling.

This test covers the sampled answer audit feature:
  1. Triangle-test: config keys exist in config.py, defaults.yaml, .env.example
  2. Sampling rate: 1-in-cfg.nlp_answer_sample_inverse answers are captured
  3. Daily cap: no more than cfg.nlp_answer_sample_daily_cap captures per day
  4. I/O failure: audit errors do not block the user
  5. PII redaction: email and phone patterns are redacted before writing
"""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from common.config import Config, cfg
from swarm.agents.nlp import NlpAnswerAgent


# ── Triangle test ──────────────────────────────────────────────────────────

def test_audit_config_keys_exist():
    """Triangle test: config keys exist in config.py, defaults.yaml, .env.example."""
    # Check Config dataclass has the fields
    assert hasattr(cfg, "nlp_answer_sample_inverse")
    assert hasattr(cfg, "nlp_answer_sample_daily_cap")
    
    # Check defaults match
    assert cfg.nlp_answer_sample_inverse == 1000
    assert cfg.nlp_answer_sample_daily_cap == 5000
    
    # Check env.example documents them
    env_example_path = Path(__file__).parents[2] / "xops" / "env" / ".env.example"
    env_text = env_example_path.read_text(encoding="utf-8")
    assert "NEGELIR_NLP_ANSWER_SAMPLE_INVERSE" in env_text
    assert "NEGELIR_NLP_ANSWER_SAMPLE_DAILY_CAP" in env_text
    
    # Check defaults.yaml documents them
    defaults_path = Path(__file__).parents[1] / "common" / "defaults.yaml"
    defaults_text = defaults_path.read_text(encoding="utf-8")
    assert "answer_sample_inverse: 1000" in defaults_text
    assert "answer_sample_daily_cap: 5000" in defaults_text


# ── Sampling rate ──────────────────────────────────────────────────────────

def test_audit_sampling_rate():
    """1-in-1000 sampling: mock random to verify sampling logic."""
    agent = NlpAnswerAgent()
    
    # Mock cfg to use sampling rate of 10 (for faster test)
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 10
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock os.path.join to use tmpdir
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                # Force random to return 1 (sampled)
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Test answer",
                        {"test": "envelope"},
                        "qa_correlation_id_1",
                    )
                
                # Force random to return 2 (not sampled)
                with mock.patch("random.randint", return_value=2):
                    agent._maybe_audit_answer(
                        "Another answer",
                        {"test": "envelope2"},
                        "qa_correlation_id_2",
                    )
                
                # Check that only the first answer was written
                audit_files = list(Path(tmpdir).rglob("*.json"))
                assert len(audit_files) == 1
                
                # Verify content
                with open(audit_files[0], "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    assert data["qa_correlation_id"] == "qa_correlation_id_1"
                    assert "Test answer" in data["answer_text_redacted"]


# ── Daily cap ──────────────────────────────────────────────────────────────

def test_audit_daily_cap():
    """Daily cap: no more than cfg.nlp_answer_sample_daily_cap captures per day."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1  # Always sample
        mock_cfg.nlp_answer_sample_daily_cap = 3  # Cap at 3
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    # Try to write 5 answers
                    for i in range(5):
                        agent._maybe_audit_answer(
                            f"Answer {i}",
                            {"index": i},
                            f"qa_corr_{i}",
                        )
                    
                    # Only 3 should be written (cap)
                    audit_files = list(Path(tmpdir).rglob("*.json"))
                    assert len(audit_files) == 3


def test_audit_daily_cap_resets_on_date_change():
    """Daily cap resets when the date changes."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    # Write 2 answers on day 1
                    with mock.patch("ai.swarm.agents.nlp._dt.datetime") as mock_dt:
                        mock_dt.now.return_value.strftime.return_value = "2026-05-01"
                        mock_dt.now.return_value.isoformat.return_value = "2026-05-01T12:00:00"
                        
                        agent._maybe_audit_answer("Day 1 answer 1", {}, "qa_1")
                        agent._maybe_audit_answer("Day 1 answer 2", {}, "qa_2")
                        agent._maybe_audit_answer("Day 1 answer 3", {}, "qa_3")  # Exceeds cap
                    
                    # Write 2 more on day 2 (should succeed after reset)
                    with mock.patch("ai.swarm.agents.nlp._dt.datetime") as mock_dt:
                        mock_dt.now.return_value.strftime.return_value = "2026-05-02"
                        mock_dt.now.return_value.isoformat.return_value = "2026-05-02T12:00:00"
                        
                        agent._maybe_audit_answer("Day 2 answer 1", {}, "qa_4")
                        agent._maybe_audit_answer("Day 2 answer 2", {}, "qa_5")
                    
                    # Total: 2 from day 1 + 2 from day 2 = 4
                    audit_files = list(Path(tmpdir).rglob("*.json"))
                    assert len(audit_files) == 4


# ── I/O failure handling ───────────────────────────────────────────────────

def test_audit_does_not_block_on_error():
    """I/O error swallowed: audit errors do not raise exceptions."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1  # Always sample
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        # Mock os.makedirs to raise an OSError
        with mock.patch("os.makedirs", side_effect=OSError("Disk full")):
            with mock.patch("random.randint", return_value=1):
                # Should not raise
                agent._maybe_audit_answer(
                    "Test answer",
                    {"test": "envelope"},
                    "qa_correlation_id",
                )


# ── PII redaction ──────────────────────────────────────────────────────────

def test_audit_redacts_email():
    """PII redaction: email patterns are redacted before writing."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Contact us at support@negelir.com for help.",
                        {"test": "envelope"},
                        "qa_email_test",
                    )
                    
                    audit_files = list(Path(tmpdir).rglob("*.json"))
                    assert len(audit_files) == 1
                    
                    with open(audit_files[0], "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        assert "support@negelir.com" not in data["answer_text_redacted"]
                        assert "[REDACTED_EMAIL]" in data["answer_text_redacted"]


def test_audit_redacts_phone():
    """PII redaction: Turkish phone patterns are redacted before writing."""
    agent = NlpAnswerAgent()
    
    with mock.patch("common.config.cfg") as mock_cfg:
        mock_cfg.nlp_answer_sample_inverse = 1
        mock_cfg.nlp_answer_sample_daily_cap = 1000
        
        with tempfile.TemporaryDirectory() as tmpdir:
            original_join = os.path.join
            
            def mock_join(*args):
                if len(args) >= 3 and args[0] == "data" and args[1] == "nlp":
                    return original_join(tmpdir, *args[2:])
                return original_join(*args)
            
            with mock.patch("os.path.join", side_effect=mock_join):
                with mock.patch("random.randint", return_value=1):
                    agent._maybe_audit_answer(
                        "Destek hattımız: 0555 123 45 67",
                        {"test": "envelope"},
                        "qa_phone_test",
                    )
                    
                    audit_files = list(Path(tmpdir).rglob("*.json"))
                    assert len(audit_files) == 1
                    
                    with open(audit_files[0], "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        assert "0555 123 45 67" not in data["answer_text_redacted"]
                        assert "[REDACTED_PHONE]" in data["answer_text_redacted"]
