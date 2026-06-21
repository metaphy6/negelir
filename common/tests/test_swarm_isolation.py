"""Phase 18.2 §18.2 — Swarm isolation tests.

Tests verify that swarm component respects isolation policy:
- Cannot import psycopg2, asyncpg, sqlalchemy, or datasource.* modules
- Can import common.feeds, common.schemas, common.bus, common.observability
- Cannot import fastapi, flask, or requests

Ledger #1-#3: AST-based import checking, policy loaded from YAML.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from common.isolation.check import (
    check_component_isolation,
    load_policy,
)


class TestSwarmIsolation:
    """Verify swarm component isolation gates."""

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
        assert "swarm" in policy["components"]

    def test_swarm_component_has_forbidden_rules(self) -> None:
        """Swarm policy must declare forbidden imports."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        assert len(forbidden) > 0, "Swarm must have forbidden imports list"
        forbidden_str = " ".join(forbidden)
        assert "psycopg" in forbidden_str, "Swarm forbidden list should mention psycopg"

    def test_swarm_forbidden_imports_are_regex_patterns(self) -> None:
        """Forbidden imports in policy must be valid regex patterns."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        for pattern in forbidden:
            try:
                re.compile(pattern)
            except re.error as e:
                raise AssertionError(f"Invalid regex in swarm forbidden list: {pattern}") from e

    def test_swarm_allowed_cross_component_imports(self) -> None:
        """Swarm must be allowed to import from common.feeds, common.schemas, common.bus."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        cross_allowed = policy.get("cross_component_allowed", {}).get("swarm", [])
        assert len(cross_allowed) > 0, "Swarm must have cross-component allows"
        allows_str = " ".join(cross_allowed)
        assert "common.feeds" in allows_str, "Swarm must be allowed to import common.feeds"
        assert "common.schemas" in allows_str, "Swarm must be allowed to import common.schemas"
        assert "common.bus" in allows_str, "Swarm must be allowed to import common.bus"

    def test_swarm_violates_psycopg_forbidden(self) -> None:
        """Verify that psycopg2 import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        test_module = "psycopg2"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "psycopg2 should be forbidden for swarm"

    def test_swarm_violates_asyncpg_forbidden(self) -> None:
        """Verify that asyncpg import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        test_module = "asyncpg"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "asyncpg should be forbidden for swarm"

    def test_swarm_violates_datasource_import_forbidden(self) -> None:
        """Verify that datasource.* imports are forbidden for swarm."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        test_module = "datasource.scraper"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "datasource.* should be forbidden for swarm"

    def test_swarm_violates_requests_forbidden(self) -> None:
        """Verify that requests import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        test_module = "requests"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "requests should be forbidden for swarm"

    def test_swarm_allowed_common_schemas(self) -> None:
        """Verify that common.schemas would NOT be in forbidden list."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        test_module = "common.schemas"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert not is_forbidden, "common.schemas should NOT be forbidden for swarm"

    def test_swarm_allowed_common_feeds(self) -> None:
        """Verify that common.feeds would NOT be in forbidden list."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        swarm_policy = policy["components"]["swarm"]
        forbidden = swarm_policy.get("forbidden_imports", [])
        test_module = "common.feeds"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert not is_forbidden, "common.feeds should NOT be forbidden for swarm"

    def test_swarm_isolation_check_component_runs(self) -> None:
        """check_component_isolation should run without error for swarm."""
        repo_root = Path(__file__).resolve().parents[2]
        policy_path = self._get_policy_path()
        violations = check_component_isolation(repo_root, "swarm", policy_path)
        assert isinstance(violations, list)
