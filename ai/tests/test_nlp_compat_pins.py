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
