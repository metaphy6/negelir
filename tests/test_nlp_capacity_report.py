"""Test Phase 10 §10.23.10 — nlp.capacity-report generator."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_nlp_capacity_report_target_exists():
    result = subprocess.run(
        ["make", "help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nlp.capacity-report" in result.stdout


def test_nlp_capacity_report_generates_artifact():
    report_path = REPO_ROOT / "data" / "nlp" / "capacity_report.md"
    if report_path.exists():
        report_path.unlink()

    result = subprocess.run(
        ["make", "nlp.capacity-report"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "# NLP Capacity Report" in content
    assert "Effective throughput" in content
    report_path.unlink()


def test_nlp_capacity_report_generated_on_cfg_change(monkeypatch: pytest.MonkeyPatch):
    report_path = REPO_ROOT / "data" / "nlp" / "capacity_report.md"
    if report_path.exists():
        report_path.unlink()

    monkeypatch.setenv("NEGELIR_NLP_INTAKE_WORKERS", "4")
    result = subprocess.run(
        ["make", "nlp.capacity-report"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "nlp_intake_workers: 4" in content
    assert "Effective throughput" in content
    report_path.unlink()


def test_nlp_capacity_model_doc_contains_required_sections():
    doc_path = REPO_ROOT / "docs" / "design" / "TURKISH_NLP.md"
    content = doc_path.read_text(encoding="utf-8")
    assert "### Capacity model (§10.23.10)" in content
    assert "throughput_pod = parallelism / avg_latency" in content
    assert "humanizer 300ms" in content
    assert "Throughput ceiling (without humanizer): `8 / 0.115s ≈ 70 QPS`" in content
