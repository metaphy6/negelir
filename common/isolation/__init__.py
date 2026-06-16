"""Phase 18.1 §18.1 — Isolation checking infrastructure.

This package contains:
- policy.yaml: per-component import policy
- check.py: Python AST-based isolation checker
- go_check.go: Go dependency checker
- graph_builder.py: import graph generation
- import_graph.snapshot.json: checked-in baseline

Public API (Phase 18.0 ledger #1):
- uses_ast_analysis(): Prove AST-based checking (not grep)
- extract_imports(): Extract imports using ast.walk (not grep)
- check_component_isolation(): Run isolation check on a component
- IsolationViolation: Data class for violation reporting
"""
from __future__ import annotations

from .check import (
    IsolationViolation,
    check_component_isolation,
    check_isolation_full,
    extract_imports,
    uses_ast_analysis,
)

__all__ = [
    "IsolationViolation",
    "check_component_isolation",
    "check_isolation_full",
    "extract_imports",
    "uses_ast_analysis",
]


