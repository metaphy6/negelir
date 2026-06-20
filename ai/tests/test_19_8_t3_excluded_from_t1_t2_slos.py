"""Phase 19 §19.8 — T3 leagues excluded from T1/T2 SLO calculations."""
import pytest


def test_t3_excluded_from_t1_t2_slos():
    """T3 leagues do not appear in T1/T2 SLO calculations."""
    from xops.leagues.slo_report import SLOReportGenerator
    
    generator = SLOReportGenerator()
    # Verify T3 leagues are filtered out
    assert generator._tier_filter("T3") is False
    assert generator._tier_filter("T1") is True
    assert generator._tier_filter("T2") is True


def test_slo_report_queries_exclude_t3():
    """SQL queries for SLO reports exclude T3 leagues."""
    from xops.leagues.slo_report import SLOReportGenerator
    
    generator = SLOReportGenerator()
    query = generator._build_query()
    assert "tier" in query and ("T1" in query and "T2" in query) and "T3" not in query
