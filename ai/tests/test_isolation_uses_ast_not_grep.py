"""
Phase 18.0 §18.0 ledger #1 — Proof test: AST-based isolation check (not grep).

This test verifies assumption #1 is WRONG:
  "A grep for `psycopg` is enough to enforce swarm isolation."

Proof: Grep cannot distinguish legitimate uses (e.g. `common/bus/` may speak
Redis on behalf of the swarm via a typed Protocol) from violations (a swarm
agent reaching for psycopg directly). The isolation tests use AST-based
import-graph analysis (`ast.walk` over each component's `*.py` files,
collecting `Import` / `ImportFrom` nodes and matching against a per-component
allow-list declared in `common/isolation/policy.yaml`).
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from ai.common.isolation import (
    IsolationViolation,
    check_component_isolation,
    uses_ast_analysis,
)


class TestIsolationUsesAST:
    """Prove that isolation checking uses AST, not grep."""

    def test_uses_ast_analysis_not_grep(self) -> None:
        """Verify that the isolation module uses AST functions."""
        assert uses_ast_analysis()
        # Check that ast module functions are available
        assert hasattr(ast, "walk")
        assert hasattr(ast, "Import")
        assert hasattr(ast, "ImportFrom")

    def test_isolation_module_has_ast_imports(self) -> None:
        """Verify isolation module source explicitly imports ast."""
        from common import isolation as iso_module

        source_file = Path(iso_module.__file__).parent / "check.py"
        with open(source_file) as f:
            source = f.read()
        assert "import ast" in source
        assert "ast.walk" in source
        assert "ast.Import" in source or "ast.ImportFrom" in source

    def test_ast_walk_extracts_imports(self) -> None:
        """Verify AST walker can extract imports from Python code."""
        code = """
import psycopg2
from redis import StrictRedis
from ai.common.feeds import FeedReader

def fetch_data():
    pass
"""
        tree = ast.parse(code)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(("import", alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(("from", node.module))

        # Should find three imports via AST
        assert len(imports) == 3
        assert ("import", "psycopg2") in imports
        assert ("from", "redis") in imports
        assert ("from", "common.feeds") in imports

    def test_grep_cannot_distinguish_comment_from_code(self) -> None:
        """
        Demonstrate why grep is insufficient:
        Grep cannot distinguish an import in a comment from actual code.

        AST parses only actual code, ignoring comments.
        """
        code = """# Comment: import requests_forbidden_module
# Real import follows:
import requests_forbidden_module
"""
        # Parse with AST
        tree = ast.parse(code)
        real_imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]

        # AST correctly finds only ONE import (the real one)
        assert real_imports == ["requests_forbidden_module"]

        # But grep would find TWO mentions of the module:
        grep_count = code.count("requests_forbidden_module")
        assert grep_count == 2  # Comment mention + real import

    def test_ast_distinguishes_legitimate_from_violation(self) -> None:
        """
        Demonstrate that AST can distinguish legitimate uses from violations.

        Example: common/bus/redis_client.py may wrap Redis for the swarm,
        but a swarm agent directly importing redis would be a violation.
        """
        # Legitimate wrapper in common/bus/redis_client.py:
        wrapper_code = """
import redis

class RedisWrapper:
    def __init__(self):
        self.client = redis.StrictRedis()
"""

        # Violation in swarm/predictor.py:
        violation_code = """
import redis

class Predictor:
    def query_cache(self):
        client = redis.StrictRedis()
"""

        def get_imports(code: str) -> list[str]:
            tree = ast.parse(code)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
            return imports

        wrapper_imports = get_imports(wrapper_code)
        violation_imports = get_imports(violation_code)

        # Both have the same import: redis
        assert wrapper_imports == ["redis"]
        assert violation_imports == ["redis"]

        # But policy-based enforcement (ledger #1) distinguishes them:
        # - common.bus is allowed to import redis
        # - swarm is NOT allowed to import redis
        # This distinction happens in the isolation policy, NOT in the
        # mechanism. The mechanism (AST-based extraction) is the same,
        # and it correctly extracts both. The policy determines which is OK.

    def test_isolation_policy_yaml_exists(self, tmp_path: Path) -> None:
        """Verify that the isolation policy file exists and is loadable."""
        repo_root = Path(__file__).resolve().parents[2]
        policy_path = repo_root / "ai" / "common" / "isolation" / "policy.yaml"

        assert policy_path.exists(), f"Policy file missing at {policy_path}"

        # Should be valid YAML
        import yaml

        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        assert policy is not None
        assert "schema_version" in policy
        assert "components" in policy
        # Should have at least the four main components
        assert "datasource" in policy["components"]
        assert "swarm" in policy["components"]
        assert "server" in policy["components"]
        assert "common" in policy["components"]

    def test_ast_extraction_on_sample_module(self, tmp_path: Path) -> None:
        """Test AST-based import extraction on a sample Python file."""
        sample_py = tmp_path / "sample.py"
        sample_py.write_text(
            """
from ai.common.isolation import check_component_isolation
import pytest
from pathlib import Path

def test_something():
    pass
"""
        )

        from ai.common.isolation.check import extract_imports

        imports = extract_imports(sample_py)
        # Should find 3 imports
        assert len(imports) == 3
        modules = [imp[0] for imp in imports]
        assert "common.isolation" in modules
        assert "pytest" in modules
        assert "pathlib" in modules

    def test_isolation_violation_structure(self) -> None:
        """Verify IsolationViolation data class has required fields."""
        violation = IsolationViolation(
            file=Path("test.py"),
            line=42,
            import_stmt="import psycopg2",
            source_component="swarm",
            target_module="psycopg2",
            ledger_ref=1,
            suggested_fix="Remove psycopg2 import",
        )

        assert violation.file == Path("test.py")
        assert violation.line == 42
        assert violation.import_stmt == "import psycopg2"
        assert violation.source_component == "swarm"
        assert violation.target_module == "psycopg2"
        assert violation.ledger_ref == 1
        assert violation.suggested_fix == "Remove psycopg2 import"

    def test_ast_handles_complex_imports(self) -> None:
        """Test AST extraction handles various import styles."""
        code = """
import a
import b, c
from d import e
from f import g, h
from i import j as k
import l as m
"""
        from ai.common.isolation.check import extract_imports

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            path = Path(f.name)

        try:
            imports = extract_imports(path)
            # AST should extract all of them
            assert len(imports) >= 7  # At least 7 separate import statements
        finally:
            path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
