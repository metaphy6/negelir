from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile import nlp as nlp_module  # noqa: E402


def test_nlp_dr_runbook_commands_registered() -> None:
    expected = {
        "nlp.lexicon-restore-from-snapshot",
        "nlp.intent-model-restore",
        "nlp.calibration-pin",
        "nlp.humanizer-rollback",
    }
    assert expected.issubset(set(nlp_module.COMMANDS))


def test_nlp_dr_runbook_dry_run_prints_intended_action(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DRY_RUN", "true")

    rc = nlp_module.cmd_nlp_lexicon_restore_from_snapshot(["--snapshot-id", "snap-abc"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "would restore lexicon snapshot snap-abc" in captured.out
    assert "dry run mode, no mutation performed" in captured.out

    rc = nlp_module.cmd_nlp_intent_model_restore(["--version", "v1.2.3"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "would restore intent model version v1.2.3" in captured.out

    rc = nlp_module.cmd_nlp_calibration_pin(["--snapshot-id", "calib-123"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "would pin calibration snapshot calib-123" in captured.out

    rc = nlp_module.cmd_nlp_humanizer_rollback(["--version", "h1.0.0"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "would rollback humanizer version to h1.0.0" in captured.out
