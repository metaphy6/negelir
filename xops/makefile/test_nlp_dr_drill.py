from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile import nlp as nlp_module  # noqa: E402


def test_nlp_dr_drill_command_registered() -> None:
    assert "nlp.dr-drill" in nlp_module.COMMANDS
    assert nlp_module.COMMANDS["nlp.dr-drill"] is nlp_module.cmd_nlp_dr_drill


def test_nlp_dr_drill_requires_confirm(capsys) -> None:
    result = nlp_module.cmd_nlp_dr_drill([])
    assert result == 1
    captured = capsys.readouterr()
    assert "requires --confirm" in captured.err.lower()


def test_nlp_dr_drill_writes_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(nlp_module, "REPO_ROOT", tmp_path)
    report_path = tmp_path / "docs" / "reports" / "nlp_dr_drill_test.md"

    result = nlp_module.cmd_nlp_dr_drill(["--confirm", "--report", str(report_path)])
    assert result == 0
    assert report_path.exists()

    content = report_path.read_text(encoding="utf-8")
    assert "# NLP Disaster Recovery Drill Report" in content
    assert "human-only" in content
