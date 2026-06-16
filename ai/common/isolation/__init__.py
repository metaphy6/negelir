"""Phase 18.0 — Swarm isolation layer."""

from .check import IsolationViolation, check_component_isolation, uses_ast_analysis

__all__ = [
    "IsolationViolation",
    "check_component_isolation",
    "uses_ast_analysis",
]
