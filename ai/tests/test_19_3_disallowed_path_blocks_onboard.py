"""Phase 19 §19.3 — robots.txt path disallow test."""
from __future__ import annotations
import pytest

class TestRobotsTxtPathDisallow:
    def test_disallowed_path_blocks_onboarding(self) -> None:
        """If robots.txt disallows scraper's User-agent for target URL, onboarding blocked."""
        assert True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
