"""Phase 19 §19.9 — New extractors obey isolation."""
import pytest


def test_new_extractor_obeys_isolation_policy():
    """Extractor imports conform to common/isolation/policy.yaml."""
    from common.isolation.policy import check_module_imports
    
    # Mock extractor module path
    result = check_module_imports("datasource/scraper/extractors/test_league/__init__.py")
    assert result is True or result.get("violations") == []
