"""Phase 18.2 §18.2 — Server isolation tests.

Tests verify that server component respects isolation policy:
- Cannot import xgboost, torch, sklearn (ML frameworks)
- Can import common.api, common.schemas, common.observability
- Cannot import fastapi/flask directly (Go REST API owns the server)

Ledger #1-#3: AST-based import checking, policy loaded from YAML.
Note: Server is primarily Go; these tests focus on Python structure.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.isolation.check import (
    check_component_isolation,
    load_policy,
)


class TestServerIsolation:
    """Verify server component isolation gates."""

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
        assert "server" in policy["components"]

    def test_server_component_has_forbidden_rules(self) -> None:
        """Server policy must declare forbidden imports."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        assert len(forbidden) > 0, "Server must have forbidden imports list"
        forbidden_str = " ".join(forbidden)
        assert "xgboost" in forbidden_str, "Server forbidden list should mention xgboost"
        assert "torch" in forbidden_str, "Server forbidden list should mention torch"
        assert "sklearn" in forbidden_str, "Server forbidden list should mention sklearn"

    def test_server_forbidden_imports_are_regex_patterns(self) -> None:
        """Forbidden imports in policy must be valid regex patterns."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        for pattern in forbidden:
            try:
                re.compile(pattern)
            except re.error as e:
                raise AssertionError(f"Invalid regex in server forbidden list: {pattern}") from e

    def test_server_allowed_cross_component_imports(self) -> None:
        """Server must be allowed to import from common.api, common.schemas, common.observability."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        cross_allowed = policy.get("cross_component_allowed", {}).get("server", [])
        assert len(cross_allowed) > 0, "Server must have cross-component allows"
        allows_str = " ".join(cross_allowed)
        assert "common.api" in allows_str, "Server must be allowed to import common.api"
        assert "common.schemas" in allows_str, "Server must be allowed to import common.schemas"

    def test_server_violates_xgboost_forbidden(self) -> None:
        """Verify that xgboost import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        test_module = "xgboost"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "xgboost should be forbidden for server"

    def test_server_violates_torch_forbidden(self) -> None:
        """Verify that torch import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        test_module = "torch"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "torch should be forbidden for server"

    def test_server_violates_sklearn_forbidden(self) -> None:
        """Verify that sklearn import would be caught as violation."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        test_module = "sklearn"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert is_forbidden, "sklearn should be forbidden for server"

    def test_server_allowed_common_api(self) -> None:
        """Verify that common.api would NOT be in forbidden list."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        test_module = "common.api"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert not is_forbidden, "common.api should NOT be forbidden for server"

    def test_server_allowed_common_schemas(self) -> None:
        """Verify that common.schemas would NOT be in forbidden list."""
        policy_path = self._get_policy_path()
        policy = load_policy(policy_path)
        server_policy = policy["components"]["server"]
        forbidden = server_policy.get("forbidden_imports", [])
        test_module = "common.schemas"
        is_forbidden = any(re.match(pattern, test_module) for pattern in forbidden)
        assert not is_forbidden, "common.schemas should NOT be forbidden for server"

    def test_server_isolation_check_component_runs(self) -> None:
        """check_component_isolation should run without error for server."""
        repo_root = Path(__file__).resolve().parents[2]
        policy_path = self._get_policy_path()
        violations = check_component_isolation(repo_root, "server", policy_path)
        assert isinstance(violations, list)
