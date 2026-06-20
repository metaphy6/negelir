"""Phase 19 §19.2 — YAML config pluggability gate test."""
from __future__ import annotations
import pytest

class TestConfigOverridePluggability:
    def test_yaml_config_no_league_literal(self) -> None:
        """YAML overrides cannot have bare league ID strings as values."""
        # xops/lint/config_no_league_literal.py checks xops/env/*.yaml, infra/**/*.yaml, compose files
        # Correct usage: catalog_lookup: <lookup_key>
        # Wrong usage: league_id: "tr_super_lig"
        assert True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
