"""Tests for Phase 19 §19.17 — API catalog surface."""

import pytest
from ai.common.catalog_api_models import (
    LeagueTier, LeagueStatus, LeagueCatalogEntry, CatalogListResponse, CatalogListRequest, LeagueReadinessScore
)


class TestCatalogListRequest:
    """§19.17: Pagination and filtering."""
    
    def test_request_validation_limit_bounds(self):
        """Limit must be within valid bounds."""
        req = CatalogListRequest(limit=0)
        valid, msg = req.validate(max_limit=50)
        assert not valid
        
        req = CatalogListRequest(limit=100)
        valid, msg = req.validate(max_limit=50)
        assert not valid
        
        req = CatalogListRequest(limit=50)
        valid, msg = req.validate(max_limit=50)
        assert valid


class TestCatalogListResponse:
    """§19.17: Catalog response structure."""
    
    def test_response_serialization(self):
        """Response can be serialized to JSON-compatible dict."""
        entry = LeagueCatalogEntry(
            league_id="tr_super_lig",
            name_en="Turkish Super Lig",
            name_tr="Türk Futbol Ligi",
            confederation="AFC",
            tier=LeagueTier.T1,
            status=LeagueStatus.ACTIVE,
            sources_count=2,
            last_fixture_date_utc="2024-12-15T19:30:00Z"
        )
        
        response = CatalogListResponse(
            leagues=[entry],
            total_count=1,
            has_more=False
        )
        
        data = response.to_dict()
        assert data['total_count'] == 1
        assert len(data['leagues']) == 1
        assert data['leagues'][0]['league_id'] == "tr_super_lig"
        assert data['leagues'][0]['tier'] == "T1"
    
    def test_response_with_readiness_score(self):
        """Response can include readiness metrics (admin only)."""
        score = LeagueReadinessScore(
            league_id="tr_super_lig",
            overall_score=92.5,
            coverage_score=95.0,
            timeliness_score=90.0,
            accuracy_score=90.0,
            team_coverage_pct=100.0,
            fixture_freshness_hours=2
        )
        
        entry = LeagueCatalogEntry(
            league_id="tr_super_lig",
            name_en="Turkish Super Lig",
            name_tr="Türk Futbol Ligi",
            confederation="AFC",
            tier=LeagueTier.T1,
            status=LeagueStatus.ACTIVE,
            sources_count=2,
            readiness_score=score
        )
        
        response = CatalogListResponse(leagues=[entry], total_count=1)
        data = response.to_dict()
        
        assert data['leagues'][0]['readiness_score'] is not None
        assert data['leagues'][0]['readiness_score']['overall_score'] == 92.5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
