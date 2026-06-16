"""Phase 18.1 §18.1 — Go isolation checker proof tests.

Verifies that common/isolation/go_check.go uses Go AST parsing and policy.yaml,
not grep, matching the Python checker's approach (ledger #3).
"""
from __future__ import annotations

import ast
from pathlib import Path


def test_go_isolation_file_exists() -> None:
    """Verify that go_check.go exists and is in the correct location."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    assert checker_path.exists(), f"go_check.go not found at {checker_path}"


def test_go_isolation_uses_ast_parsing() -> None:
    """Verify that go_check.go uses Go AST parsing, not grep."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should use go/ast package for parsing
    assert "go/ast" in content, "go_check.go should import go/ast"
    assert "ast.Inspect" in content, "go_check.go should use ast.Inspect"
    
    # Should NOT use simple string matching (grep-like)
    assert "strings.Contains" not in content or "grep" not in content.lower(), (
        "go_check.go should use AST parsing, not grep"
    )


def test_go_isolation_loads_policy_yaml() -> None:
    """Verify that go_check.go loads policy.yaml for configuration."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should reference policy.yaml
    assert "policy" in content.lower(), "go_check.go should reference policy"
    assert "yaml" in content.lower(), "go_check.go should parse YAML"
    assert "PolicyFile" in content, "go_check.go should define a PolicyFile structure"


def test_go_isolation_detects_exec_command() -> None:
    """Verify that go_check.go looks for os/exec.Command patterns."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should detect exec.Command calls
    assert "exec.Command" in content or "Command" in content, (
        "go_check.go should detect os/exec.Command invocations"
    )
    assert "isExecCommand" in content, "go_check.go should have a function to detect exec calls"


def test_go_isolation_identifies_forbidden_binaries() -> None:
    """Verify that go_check.go tracks forbidden binary list."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should have list of forbidden binaries
    assert "forbiddenBinaries" in content, "go_check.go should define forbidden binaries"
    
    # Should include at least some of the key forbidden binaries
    expected = ["python", "pytest", "xgboost", "torch", "pip"]
    for binary in expected:
        assert binary in content, f"go_check.go should mention forbidden binary: {binary}"


def test_go_isolation_returns_structured_violations() -> None:
    """Verify that go_check.go returns structured violation records."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should define IsolationViolation structure matching Python version
    assert "IsolationViolation" in content, "go_check.go should define IsolationViolation struct"
    assert "type IsolationViolation struct" in content, (
        "go_check.go should have a struct definition for violations"
    )
    
    # Should include key fields
    fields = ["File", "Line", "ExecStmt", "SourceComponent", "ForbiddenBinary", "LedgerRef"]
    for field in fields:
        assert field in content, f"IsolationViolation should have {field} field"


def test_go_isolation_command_signature() -> None:
    """Verify that go_check.go has the right command interface."""
    checker_path = Path(__file__).resolve().parents[2] / "common" / "isolation" / "go_check.go"
    content = checker_path.read_text()
    
    # Should respond to check-server command
    assert "check-" in content or "checkComponent" in content, (
        "go_check.go should implement check-<component> command interface"
    )
