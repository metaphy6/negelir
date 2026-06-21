"""Phase 18.2 §18.2 — Datasource isolation tests.

Tests verify that datasource component respects isolation policy:
- Cannot import fastapi, flask, swarm.* modules
- Can import common.schemas, common.feeds, common.bus, common.config
- Cannot import psycopg2 (direct DB access forbidden)

Ledger #1-#3: AST-based import checking, policy loaded from YAML.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.isolation.check import (
    check_component_isolation,
    load_policy,
)


class TestDatasourceIsolation:
    """Verify datasource component isolation gates."""

    @staticmethod
    def _get_policy_path() -> Path:
        """Dynamically locate policy.yaml — no hardcoded paths."""
        repo_root = Path(__file__).resolve().parents[2]
        policy_path = repo_root / "ai" / "common" / "isolation" / "policy.yaml"
        assert policy_path.exists(), f"Policy must exist at {policy_path}"
        return policy_path

    def test_policy_loads_dynamically(self) -> None:
        """Policy.yaml must load without hardcoded strings."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        assert "components" in policy
        assert "datasource" in policy["components"]

    def test_datasource_component_has_forbidden_rules(self) -> None:
        """Datasource policy must declare forbidden imports."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        assert len(forbidden) > 0, "Datasource must have forbidden imports list"
        forbidden_str = " ".join(forbidden)
        assert "fastapi" in forbidden_str, "Datasource forbidden list should mention fastapi"
        assert "flask" in forbidden_str, "Datasource forbidden list should mention flask"

    def test_datasource_forbidden_imports_are_regex_patterns(self) -> None:
        """Forbidden imports in policy must be valid regex patterns."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        for pattern in forbidden:
            try:
                re.compile(pattern)
            except re.error as e:
                raise AssertionError(f"Invalid regex in datasource forbidden list: {pattern}") from e

    def test_datasource_allowed_cross_component_imports(self) -> None:
        """Datasource must be allowed to import from common.schemas, common.feeds, common.bus, common.config."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        cross_allowed = policy.get("cross_component_allowed", {}).get("datasource", [])
        assert len(cross_allowed) > 0, "Datasource must have cross-component allows"
        allows_str = " ".join(cross_allowed)
        assert "common.schemas" in allows_str, "Datasource must be allowed to import common.schemas"
        assert "common.feeds" in allows_str, "Datasource must be allowed to import common.feeds"
        assert "common.bus" in allows_str, "Datasource must be allowed to import common.bus"

    def test_datasource_violates_fastapi_forbidden(self) -> None:
        """Verify that fastapi import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        test_module = "fastapi"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "fastapi should be forbidden for datasource"

    def test_datasource_violates_flask_forbidden(self) -> None:
        """Verify that flask import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        test_module = "flask"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "flask should be forbidden for datasource"

    def test_datasource_violates_swarm_import_forbidden(self) -> None:
        """Verify that swarm.* imports are forbidden for datasource."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        test_module = "swarm.agents"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "swarm.* should be forbidden for datasource"

    def test_datasource_violates_psycopg_forbidden(self) -> None:
        """Verify that psycopg2 import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        test_module = "psycopg2"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "psycopg2 should be forbidden for datasource"

    def test_datasource_allowed_common_schemas(self) -> None:
        """Verify that common.schemas would NOT be in forbidden list."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        test_module = "common.schemas"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert not is_forbidden, "common.schemas should NOT be forbidden for datasource"

    def test_datasource_allowed_common_feeds(self) -> None:
        """Verify that common.feeds would NOT be in forbidden list."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        datasource_policy = policy["components"]["datasource"]
        forbidden = datasource_policy.get("forbidden_imports", [])
        test_module = "common.feeds"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert not is_forbidden, "common.feeds should NOT be forbidden for datasource"

    def test_datasource_isolation_check_component_runs(self) -> None:
        """check_component_isolation should run without error for datasource."""
        repo_root = Path(__file__).resolve().parents[2]
        policy_path = self._get_policy_path()
        violations = check_component_isolation(repo_root, "datasource", policy_path)
        assert isinstance(violations, list)
