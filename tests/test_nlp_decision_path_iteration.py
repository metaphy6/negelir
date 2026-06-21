"""Phase 10 §10.21.1 — AST guard: no unsorted iteration in decision paths.

Enforces deterministic iteration over sets and dicts across the entire NLP
codebase (`ai/nlp/**` + `ai/swarm/agents/nlp/**`). Iteration over `set(...)`,
`frozenset(...)`, `dict.keys()`, `dict.items()`, `dict.values()` without a
wrapping `sorted(...)` is rejected (or `OrderedDict` / `tuple` literal).

This extends the existing §10.1 guard (normalize-only) to all NLP code:
intent classifier post-processing, entity conflict resolution, dispatcher
routing, template slot ordering, citation block construction.

Anchor: Phase 10 §10.21.1 item 1 (docs/design/phase10/sections/21-integrity-and-second-order-safety.md).
"""
from __future__ import annotations

import ast
import pathlib
from typing import List


class TestDecisionPathIteration:
    """§10.21.1: Iteration must be deterministic (no hash-order dependency)."""

    def test_nlp_no_unsorted_iteration_in_decision_path(self) -> None:
        """AST guard: reject bare set/dict iteration without sorted() across NLP code."""
        
        # Paths to scan
        ai_dir = pathlib.Path(__file__).parent.parent
        nlp_path = ai_dir / "nlp"
        swarm_nlp_path = ai_dir / "swarm" / "agents" / "nlp"
        
        scan_paths = []
        if nlp_path.exists():
            scan_paths.extend(nlp_path.rglob("*.py"))
        if swarm_nlp_path.exists():
            scan_paths.extend(swarm_nlp_path.rglob("*.py"))
        
        def _is_sorted(node: ast.expr) -> bool:
            """Check if node is wrapped in sorted()."""
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "sorted"
            )
        
        def _is_ordered_dict(node: ast.expr) -> bool:
            """Check if node is OrderedDict construction."""
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                return node.func.id == "OrderedDict"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                return node.func.attr == "OrderedDict"
            return False
        
        def _is_tuple_literal(node: ast.expr) -> bool:
            """Check if node is a tuple literal."""
            return isinstance(node, ast.Tuple)
        
        def _is_bare_unordered(node: ast.expr) -> bool:
            """Check if node is an unordered collection that needs sorting."""
            # set(...) or frozenset(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("set", "frozenset"):
                    return True
            
            # dict.keys(), dict.items(), dict.values()
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("keys", "items", "values"):
                    return True
            
            # Set literal {1, 2, 3}
            if isinstance(node, ast.Set):
                return True
            
            return False
        
        violations: List[str] = []
        
        class _Checker(ast.NodeVisitor):
            def __init__(self, filepath: pathlib.Path):
                self.filepath = filepath
            
            def _check(self, iter_node: ast.expr, lineno: int) -> None:
                # Allow sorted(), OrderedDict, tuple literals
                if _is_sorted(iter_node):
                    return
                if _is_ordered_dict(iter_node):
                    return
                if _is_tuple_literal(iter_node):
                    return
                
                # Reject bare unordered iteration
                if _is_bare_unordered(iter_node):
                    rel_path = self.filepath.relative_to(ai_dir)
                    violations.append(
                        f"{rel_path}:{lineno}: bare set/frozenset/dict.keys()/"
                        f"dict.items()/dict.values() iteration without sorted() — "
                        f"violates §10.21.1 determinism"
                    )
            
            def visit_For(self, node: ast.For) -> None:  # type: ignore[override]
                self._check(node.iter, node.lineno)
                self.generic_visit(node)
            
            def visit_ListComp(self, node: ast.ListComp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)
            
            def visit_SetComp(self, node: ast.SetComp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)
            
            def visit_DictComp(self, node: ast.DictComp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)
            
            def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)
        
        # Walk all Python files in nlp and swarm/agents/nlp
        for py_file in scan_paths:
            # Skip __pycache__ and test files
            if "__pycache__" in str(py_file):
                continue
            if "test_" in py_file.name:
                continue
            
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
                _Checker(py_file).visit(tree)
            except SyntaxError:
                # Skip files with syntax errors (might be templates or data)
                continue
        
        assert violations == [], (
            "NLP code has hash-order-dependent iterations (violates §10.21.1 "
            "determinism guarantee):\n" + "\n".join(violations)
        )
