"""Test Phase 10 §10.18 — nlp.eval-diff regression diff report."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_nlp_eval_diff_command_exists():
    """The make nlp.eval-diff target exists and can be invoked."""
    result = subprocess.run(
        ["make", "help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nlp.eval-diff" in result.stdout


def test_lint_script_exists():
    """The CI lint script exists and is executable."""
    lint_script = REPO_ROOT / "xops" / "lint" / "nlp_eval_diff_present.py"
    assert lint_script.exists()
    assert lint_script.stat().st_mode & 0o111


def test_golden_corpus_accessible():
    """The turkish_queries.yaml golden corpus exists and is readable."""
    corpus_path = REPO_ROOT / "ai" / "tests" / "fixtures" / "turkish_queries.yaml"
    assert corpus_path.exists()
    
    import yaml
    data = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    assert "corpus" in data
    assert len(data["corpus"]) >= 250
