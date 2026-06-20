"""Phase 19 §19.9 — robots.txt fields required in source registry."""
import pytest


def test_source_robots_fields_required():
    """Source entry has robots_txt_reviewed, crawl_delay_s, robots_txt_hash."""
    from xops.mock import sources
    from xops.lint.source_robots_compliance import check_source_robots_fields
    
    result = check_source_robots_fields()
    assert result is True or result.get("missing_fields") == []
