"""Phase 19 §19.8 — Readiness report is machine-readable."""
import pytest
import json
import yaml


def test_readiness_report_machine_readable_json():
    """Readiness report can be output as structured JSON."""
    from xops.leagues.readiness import ReadinessReporter
    
    reporter = ReadinessReporter()
    # Mock league
    report = reporter.generate_report("br_serie_a", output_format="json")
    
    # Must be valid JSON
    parsed = json.loads(report)
    assert "league_id" in parsed
    assert "target_tier" in parsed
    assert "checklist" in parsed or "overall_ready" in parsed


def test_readiness_report_machine_readable_yaml():
    """Readiness report can be output as structured YAML."""
    from xops.leagues.readiness import ReadinessReporter
    
    reporter = ReadinessReporter()
    report = reporter.generate_report("br_serie_a", output_format="yaml")
    
    # Must be valid YAML
    parsed = yaml.safe_load(report)
    assert isinstance(parsed, dict)
    assert "league_id" in parsed
