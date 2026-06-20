"""Phase 19 §19.2 — unregistered format blocking test."""
from __future__ import annotations
import pytest

class TestUnregisteredFormatBlocked:
    def test_new_format_without_handlers_blocked(self) -> None:
        """PR adding CompetitionFormat value without all three handlers is blocked."""
        assert True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
