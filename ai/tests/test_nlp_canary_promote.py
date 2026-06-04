from __future__ import annotations

import importlib
import json

from xops.makefile.nlp import cmd_nlp_canary_promote, cmd_nlp_canary_rollback, cmd_nlp_weekly_eval


def _reload_config():
    from common import config as _cm

    importlib.reload(_cm)
    return _cm


def test_nlp_canary_promote_passes_when_all_gates_are_met(monkeypatch):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MIN_SHADOW_HOURS", "72")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_DISAGREEMENT_RATE", "0.03")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_CONFIDENCE_DRIFT", "0.05")
    _reload_config()

    rc = cmd_nlp_canary_promote([
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.02",
        "--confidence-drift",
        "0.03",
        "--eval-harness",
        "pass",
    ])

    assert rc == 0


def test_nlp_canary_promote_passes_for_lexicon_target(monkeypatch, capsys):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MIN_SHADOW_HOURS", "72")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_DISAGREEMENT_RATE", "0.03")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_CONFIDENCE_DRIFT", "0.05")
    _reload_config()

    rc = cmd_nlp_canary_promote([
        "--target",
        "lexicon",
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.02",
        "--confidence-drift",
        "0.03",
        "--eval-harness",
        "pass",
    ])

    captured = capsys.readouterr()
    json_start = captured.out.index("{")
    json_end = captured.out.rindex("}") + 1
    payload = json.loads(captured.out[json_start:json_end])

    assert rc == 0
    assert payload["target"] == "lexicon"
    assert payload["gates_failed"] == []


def test_nlp_weekly_eval_passes_when_accuracy_drop_is_within_threshold(monkeypatch):
    monkeypatch.setenv("NEGELIR_NLP_WEEKLY_EVAL_MAX_ACCURACY_DROP", "0.03")
    monkeypatch.setenv("NEGELIR_NLP_WEEKLY_EVAL_SAMPLE_SIZE", "2000")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_POD", "0")
    _reload_config()

    rc = cmd_nlp_weekly_eval([
        "--prior-accuracy",
        "0.96",
        "--current-accuracy",
        "0.94",
    ])

    assert rc == 0


def test_nlp_weekly_eval_fails_and_emits_regression_alert_when_accuracy_drops(monkeypatch, capsys):
    monkeypatch.setenv("NEGELIR_NLP_WEEKLY_EVAL_MAX_ACCURACY_DROP", "0.01")
    _reload_config()

    rc = cmd_nlp_weekly_eval([
        "--prior-accuracy",
        "0.96",
        "--current-accuracy",
        "0.94",
        "--slice",
        "intent_class",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "nlp_weekly_eval_regression" in captured.out
    assert "accuracy_drop" in captured.out
    assert "REGRESSION" in captured.err


def test_nlp_canary_promote_refuses_below_min_shadow_hours(monkeypatch, capsys):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MIN_SHADOW_HOURS", "72")
    _reload_config()

    rc = cmd_nlp_canary_promote([
        "--shadow-hours",
        "48",
        "--disagreement-rate",
        "0.01",
        "--confidence-drift",
        "0.01",
        "--eval-harness",
        "pass",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "min_shadow_hours" in captured.out
    assert "REFUSED" in captured.err


def test_nlp_canary_promote_refuses_on_disagreement_breach(monkeypatch, capsys):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_DISAGREEMENT_RATE", "0.03")
    _reload_config()

    rc = cmd_nlp_canary_promote([
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.05",
        "--confidence-drift",
        "0.02",
        "--eval-harness",
        "pass",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "disagreement_rate" in captured.out
    assert "REFUSED" in captured.err


def test_nlp_canary_promote_refuses_on_eval_harness_fail(monkeypatch, capsys):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    _reload_config()

    rc = cmd_nlp_canary_promote([
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.01",
        "--confidence-drift",
        "0.01",
        "--eval-harness",
        "fail",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "eval_harness" in captured.out
    assert "REFUSED" in captured.err


def test_nlp_canary_promote_refuses_on_consecutive_regression_without_ack(monkeypatch, capsys):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MIN_SHADOW_HOURS", "72")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_DISAGREEMENT_RATE", "0.03")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_CONFIDENCE_DRIFT", "0.05")
    monkeypatch.setenv("NEGELIR_NLP_WEEKLY_EVAL_CONSECUTIVE_DROP_THRESHOLD", "0.05")
    _reload_config()

    rc = cmd_nlp_canary_promote([
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.01",
        "--confidence-drift",
        "0.01",
        "--weekly-eval-consecutive-drop",
        "0.06",
        "--eval-harness",
        "pass",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "weekly_eval_ack_missing" in captured.out
    assert "REFUSED" in captured.err


def test_nlp_canary_promote_passes_with_consecutive_regression_ack(monkeypatch, tmp_path):
    monkeypatch.setenv("NEGELIR_NLP_INTENT_SHADOW_MODE", "on")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MIN_SHADOW_HOURS", "72")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_DISAGREEMENT_RATE", "0.03")
    monkeypatch.setenv("NEGELIR_NLP_CANARY_MAX_CONFIDENCE_DRIFT", "0.05")
    monkeypatch.setenv("NEGELIR_NLP_WEEKLY_EVAL_CONSECUTIVE_DROP_THRESHOLD", "0.05")
    _reload_config()

    ack_path = tmp_path / "ack.yaml"
    ack_path.write_text("acknowledged\n")

    rc = cmd_nlp_canary_promote([
        "--shadow-hours",
        "72",
        "--disagreement-rate",
        "0.01",
        "--confidence-drift",
        "0.01",
        "--weekly-eval-consecutive-drop",
        "0.06",
        "--weekly-eval-ack-path",
        str(ack_path),
        "--eval-harness",
        "pass",
    ])

    assert rc == 0


def test_nlp_canary_rollback_emits_alert(capsys):
    rc = cmd_nlp_canary_rollback([
        "--target",
        "lexicon",
        "--reason",
        "failed evaluation",
    ])

    captured = capsys.readouterr()
    json_start = captured.out.index("{")
    json_end = captured.out.rindex("}") + 1
    payload = json.loads(captured.out[json_start:json_end])

    assert rc == 0
    assert payload["status"] == "rolled_back"
    assert payload["target"] == "lexicon"
    assert payload["reason"] == "failed evaluation"
    alert = payload["rollback_alert"]
    assert alert["kind"] == "nlp_canary_rolled_back"
    assert alert["severity"] == "warn"
    assert alert["subject"] == "lexicon"
    assert alert["source"] == "nlp.canary_rollback.v1"


def test_nlp_weekly_eval_workflow_exists() -> None:
    """Verify the Phase 10 weekly evaluation CI workflow file exists."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    workflow = root / "xops" / "ci" / "nlp_weekly_eval.yml"
    assert workflow.exists(), "xops/ci/nlp_weekly_eval.yml must exist for weekly NLP evaluation"


def test_nlp_cve_scan_ci_job_present() -> None:
    """Verify the Phase 10 NLP CVE scan CI workflow file exists."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    workflow = root / "xops" / "ci" / "nlp_cve_scan.yml"
    assert workflow.exists(), "xops/ci/nlp_cve_scan.yml must exist for NLP CVE scanning"


def test_nlp_runbook_cve_response_section_present() -> None:
    from pathlib import Path

    runbook = Path("docs/guides/nlp_runbook.md")
    text = runbook.read_text(encoding="utf-8")
    assert "Dependency CVE response" in text
    assert "patch ship target ≤ 24h" in text


def test_nlp_phase10_23_docs_extensions_present() -> None:
    from pathlib import Path

    doc = Path("docs/design/TURKISH_NLP.md").read_text(encoding="utf-8")
    runbook = Path("docs/guides/nlp_runbook.md").read_text(encoding="utf-8")

    assert "Output formatting (§10.23.5)" in doc
    assert "Accessibility (§10.23.7)" in doc
    assert "Tenant-Fairness (§10.23.1)" in doc
    assert "Canary rollout playbook" in runbook
    assert "Weekly-eval triage" in runbook
    assert "Cost-budget tuning" in runbook


def test_nlp_mitigations_catalogue_present() -> None:
    from pathlib import Path

    mitigations = Path("ai/nlp/security/mitigations.md")
    text = mitigations.read_text(encoding="utf-8")
    assert mitigations.exists(), "ai/nlp/security/mitigations.md must exist"
    assert "Jinja2 / template rendering" in text
