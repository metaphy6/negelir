"""Phase 18.1 §18.1 — Isolation checking infrastructure (Phase 22.3b symbol-union merge).

This package contains:
- policy.yaml: per-component import policy
- check.py: Python AST-based isolation checker
- go_check.go: Go dependency checker
- graph_builder.py: import graph generation
- import_graph.snapshot.json: checked-in baseline

Public API (Phase 18.0 ledger #1 + Phase 22.3b AI-unique symbols):
- uses_ast_analysis(): Prove AST-based checking (not grep)
- extract_imports(): Extract imports using ast.walk (not grep)
- check_component_isolation(): Run isolation check on a component
- IsolationViolation: Data class for violation reporting
- PublicSymbolViolation: Data class for public-symbol violations (ledger #25)
- load_policy(): Load policy from YAML
- get_component_for_path(): Map file paths to components
- extract_all_from_module(): Extract __all__ from module
- extract_cross_component_imports(): Find cross-component imports
- check_isolation(): Check imports against policy
- check_public_symbols(): Check public-symbol usage
- check_isolation_full(): Full isolation check (backwards compat)
"""
from __future__ import annotations

from .check import (
    IsolationViolation,
    PublicSymbolViolation,
    check_component_isolation,
    check_isolation,
    check_isolation_full,
    check_public_symbols,
    extract_all_from_module,
    extract_cross_component_imports,
    extract_imports,
    get_component_for_path,
    load_policy,
    uses_ast_analysis,
)

__all__ = [
    "IsolationViolation",
    "PublicSymbolViolation",
    "check_component_isolation",
    "check_isolation",
    "check_isolation_full",
    "check_public_symbols",
    "extract_all_from_module",
    "extract_cross_component_imports",
    "extract_imports",
    "get_component_for_path",
    "load_policy",
    "uses_ast_analysis",
]


