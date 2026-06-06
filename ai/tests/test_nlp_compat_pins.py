from __future__ import annotations

import json
from pathlib import Path


def test_nlp_cve_scan_uses_pinned_pip_audit_version() -> None:
    config = Path("xops/ci/nlp_cve_scan.yml").read_text(encoding="utf-8")
    assert "python -m pip install pip-audit==5.0.0" in config


def test_nlp_dev_requirements_pins_optional_babel() -> None:
    requirements = Path("ai/requirements-dev.txt").read_text(encoding="utf-8")
    assert "babel==2.13.1" in requirements
    assert "pip-audit==5.0.0" in requirements


def test_chart_json_zoneinfo_source_spec_includes_baseline() -> None:
    chart = json.loads(Path("xops/versioning/chart.json").read_text(encoding="utf-8"))
    source_spec = chart["compatibility"]["data_files"]["zoneinfo_file"]["source_spec"]
    assert "2026a" in source_spec


def test_chart_json_phase10_25_data_files_are_pinned() -> None:
    chart = json.loads(Path("xops/versioning/chart.json").read_text(encoding="utf-8"))
    data_files = chart["compatibility"]["data_files"]
    assert "hijri_table" in data_files, "hijri_table missing from chart.json compatibility"
    assert data_files["hijri_table"]["sha256"] == "3799ccb486995f306bb15618a6e2c8dfcb6d44d7624fa79a68818229535adcd2"
    assert "diyanet_override_table" in data_files, "diyanet_override_table missing from chart.json compatibility"
    assert data_files["diyanet_override_table"]["sha256"] == "f5d34ac3633c574d5676fb22c96a093df31f149977a5dadbe67e56af1a3d1298"
    assert "openfootball_fifa_window_seed" in data_files, "openfootball_fifa_window_seed missing from chart.json compatibility"
    assert data_files["openfootball_fifa_window_seed"]["sha256"] == "6bfa0c16f87ea59ab79c60873ad3d3c0288e3198e4d6d0f56a2ebcb117e708c4"
    assert "python_multiprocessing_glibc_range" in data_files, "python_multiprocessing_glibc_range missing from chart.json compatibility"
    assert "glibc" in data_files["python_multiprocessing_glibc_range"]["source_spec"]
