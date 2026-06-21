from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.config import cfg
from nlp.compat import CompatibilityMatrixError


def _write_matrix(tmp_path: Path, pipeline_version: str, **overrides) -> Path:
    row = {
        "pipeline_version": pipeline_version,
        "template_git_sha": "",
        "lexicon_set_sha": "",
        "intent_model_sha": "",
        "crf_model_sha": "",
        "humanizer_model_sha": "",
        "calibration_version_min": "0.0.0",
        "calibration_version_max": "999.999.999",
        "introduced_at_utc": "2026-06-01T00:00:00Z",
    }
    row.update(overrides)

    path = tmp_path / "compatibility_matrix.json"
    path.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    return path


def test_nlp_compat_matrix_loaded_at_boot(monkeypatch, tmp_path):
    matrix_path = _write_matrix(tmp_path, "10.0.0")
    monkeypatch.setattr(cfg, "nlp_compatibility_matrix_path", str(matrix_path))
    monkeypatch.setattr(cfg, "nlp_pipeline_version", "10.0.0")

    with patch("swarm.agents.nlp._enforce_nlp_spool_audit_dir_modes"), patch(
        "swarm.agents.nlp._enforce_nlp_runtime_locale"
    ):
        from swarm.agents.nlp import NlpAnswerAgent

        agent = NlpAnswerAgent(deduper=MagicMock())

    assert agent is not None


def test_nlp_compat_quartet_mismatch_refuses_boot(monkeypatch, tmp_path):
    matrix_path = _write_matrix(
        tmp_path,
        "10.0.0",
        template_git_sha="deadbeef",
    )
    monkeypatch.setattr(cfg, "nlp_compatibility_matrix_path", str(matrix_path))
    monkeypatch.setattr(cfg, "nlp_pipeline_version", "10.0.0")
    monkeypatch.setattr(cfg, "nlp_template_git_sha", "cafebabe")

    with patch("swarm.agents.nlp._enforce_nlp_spool_audit_dir_modes"), patch(
        "swarm.agents.nlp._enforce_nlp_runtime_locale"
    ):
        from swarm.agents.nlp import NlpAnswerAgent

        with pytest.raises(CompatibilityMatrixError, match="template git SHA mismatch"):
            NlpAnswerAgent(deduper=MagicMock())


def test_nlp_compat_matrix_append_only_no_row_mutation(tmp_path):
    matrix_path = tmp_path / "compatibility_matrix.json"
    rows = [
        {
            "pipeline_version": "10.0.0",
            "template_git_sha": "",
            "lexicon_set_sha": "",
            "intent_model_sha": "",
            "crf_model_sha": "",
            "humanizer_model_sha": "",
            "calibration_version_min": "0.0.0",
            "calibration_version_max": "999.999.999",
            "introduced_at_utc": "2026-06-01T00:00:00Z",
        },
        {
            "pipeline_version": "10.0.0",
            "template_git_sha": "",
            "lexicon_set_sha": "",
            "intent_model_sha": "",
            "crf_model_sha": "",
            "humanizer_model_sha": "",
            "calibration_version_min": "0.0.0",
            "calibration_version_max": "999.999.999",
            "introduced_at_utc": "2026-06-01T00:00:00Z",
        },
    ]
    matrix_path.write_text(json.dumps({"rows": rows}), encoding="utf-8")

    with pytest.raises(CompatibilityMatrixError, match="duplicate pipeline_version"):
        from nlp.compat import load_compatibility_matrix

        load_compatibility_matrix(matrix_path)


def test_nlp_pipeline_version_bumped_when_quartet_changed(monkeypatch, tmp_path):
    matrix_path = _write_matrix(tmp_path, "10.0.0")
    monkeypatch.setattr(cfg, "nlp_compatibility_matrix_path", str(matrix_path))
    monkeypatch.setattr(cfg, "nlp_pipeline_version", "10.0.1")

    from nlp.compat import validate_compatibility_matrix

    with pytest.raises(CompatibilityMatrixError, match="not found in compatibility matrix"):
        validate_compatibility_matrix()


def test_nlp_humanizer_model_sha_matches_chart(monkeypatch, tmp_path):
    from pathlib import Path

    chart_path = Path(__file__).parents[2] / "xops" / "versioning" / "chart.json"
    chart = json.loads(chart_path.read_text(encoding="utf-8"))
    expected_sha = (
        chart.get("compatibility", {})
        .get("data_files", {})
        .get("humanizer_llm", {})
        .get("sha256", "")
    )
    assert expected_sha, "chart.json must declare humanizer_llm.sha256 for this test"

    matrix_path = _write_matrix(
        tmp_path,
        "10.0.0",
        humanizer_model_sha="deadbeef",
    )
    monkeypatch.setattr(cfg, "nlp_compatibility_matrix_path", str(matrix_path))
    monkeypatch.setattr(cfg, "nlp_pipeline_version", "10.0.0")

    from nlp.compat import validate_compatibility_matrix

    with pytest.raises(CompatibilityMatrixError, match="humanizer model SHA mismatch"):
        validate_compatibility_matrix()

    matrix_path.write_text(json.dumps({"rows": [{
        "pipeline_version": "10.0.0",
        "template_git_sha": "",
        "lexicon_set_sha": "",
        "intent_model_sha": "",
        "crf_model_sha": "",
        "humanizer_model_sha": expected_sha,
        "calibration_version_min": "0.0.0",
        "calibration_version_max": "999.999.999",
        "introduced_at_utc": "2026-06-01T00:00:00Z",
    }]}), encoding="utf-8")

    validate_compatibility_matrix()
