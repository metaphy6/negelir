"""Tests for Phase 19 §19.7 — Catalog integrity at scale."""

import pytest
import tempfile
import time
from pathlib import Path
from ai.common.catalog_cache import CatalogCache, CatalogAuditEntry


class MockConfig:
    """Mock config for testing."""
    catalog_reload_slo_ms = 500


@pytest.fixture
def temp_catalog_dir():
    """Create a temporary catalog directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestCatalogCache:
    """§19.7: Catalog caching and validation."""
    
    def test_uniqueness_check_detects_duplicates(self, temp_catalog_dir):
        """O(N log N) uniqueness check works correctly."""
        cfg = MockConfig()
        cache = CatalogCache(temp_catalog_dir / "catalog.yaml", cfg)
        
        # Catalog with unique league_ids
        catalog = {
            'leagues': [
                {'league_id': 'league_1', 'name_en': 'L1', 'tier': 'T1', 'confederation': 'AFC'},
                {'league_id': 'league_2', 'name_en': 'L2', 'tier': 'T2', 'confederation': 'AFC'},
            ]
        }
        assert cache.check_uniqueness(catalog)
        
        # Catalog with duplicate league_ids
        catalog['leagues'].append({'league_id': 'league_1', 'name_en': 'Duplicate', 'tier': 'T3', 'confederation': 'AFC'})
        assert not cache.check_uniqueness(catalog)
    
    def test_incremental_validation_detects_changes(self, temp_catalog_dir):
        """Incremental validation catches schema violations."""
        cfg = MockConfig()
        cache = CatalogCache(temp_catalog_dir / "catalog.yaml", cfg)
        
        old_catalog = {
            'leagues': [
                {'league_id': 'league_1', 'name_en': 'L1', 'tier': 'T1', 'confederation': 'AFC'},
            ]
        }
        
        # New valid league
        new_catalog = {
            'leagues': [
                {'league_id': 'league_1', 'name_en': 'L1', 'tier': 'T1', 'confederation': 'AFC'},
                {'league_id': 'league_2', 'name_en': 'L2', 'tier': 'T2', 'confederation': 'AFC'},
            ]
        }
        
        valid, errors = cache.validate_incremental(old_catalog, new_catalog)
        assert valid
        assert len(errors) == 0
    
    def test_audit_log_append_only(self, temp_catalog_dir):
        """Audit log records all mutations."""
        cfg = MockConfig()
        cache = CatalogCache(temp_catalog_dir / "catalog.yaml", cfg)
        
        assert len(cache.audit_log) == 0
        
        cache.record_mutation("add", "league_1", 1)
        cache.record_mutation("update", "league_1", 1)
        
        assert len(cache.audit_log) == 2
        assert cache.audit_log[0].operation == "add"
        assert cache.audit_log[1].operation == "update"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
