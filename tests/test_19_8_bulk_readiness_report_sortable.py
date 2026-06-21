"""Phase 19 §19.8 — Bulk readiness report is sortable by promotion readiness."""
import pytest
import yaml


def test_bulk_readiness_report_sortable():
    """Bulk readiness report has promotion_readiness_score and is sorted."""
    from xops.leagues.readiness import ReadinessReporter
    
    reporter = ReadinessReporter()
    report = reporter.generate_bulk_report()
    
    # Parse YAML
    data = yaml.safe_load(report)
    assert "leagues" in data
    
    # Each league should have a score
    for league in data["leagues"]:
        assert "league_id" in league
        assert "promotion_readiness_score" in league
        assert isinstance(league["promotion_readiness_score"], (int, float))
    
    # Verify sorted descending
    scores = [l["promotion_readiness_score"] for l in data["leagues"]]
    assert scores == sorted(scores, reverse=True)


def test_bulk_report_completeness():
    """Bulk report has valid structure."""
    from xops.leagues.readiness import ReadinessReporter
    
    reporter = ReadinessReporter()
    report = reporter.generate_bulk_report()
    
    data = yaml.safe_load(report)
    assert "leagues" in data
    assert isinstance(data["leagues"], list)
    # The list may be empty in test environments with no T3 leagues
    # That's OK - we're testing the structure, not the content
