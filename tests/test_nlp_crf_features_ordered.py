"""Phase 10 §10.21.1 — AST guard: CRF feature builders must use ordered structures.

Enforces deterministic feature extraction for CRF models by rejecting dict(...)
literals in CRF feature builder functions. python-crfsuite Tagger.tag() is
deterministic, but feature-extraction order isn't if features are dicts.

This AST guard rejects dict(...) literal (and {...} dict literals) in
feature builder functions, requiring list[tuple[str, float]] or list[str]
(insertion-ordered + explicit).

Anchor: Phase 10 §10.21.1 item 5 (docs/design/phase10/sections/21-integrity-and-second-order-safety.md line 19).
"""
from __future__ import annotations

import ast
import pathlib
from typing import List

import pytest


class TestCrfFeaturesDeterminism:
    """§10.21.1: CRF feature extractors must use ordered structures (not dicts)."""

    def test_nlp_crf_features_are_ordered(self) -> None:
        """AST guard: reject dict(...) literals in CRF feature builders."""
        
        # Path to scan (entity.py contains the CRF feature builder)
        ai_dir = pathlib.Path(__file__).parent.parent
        entity_path = ai_dir / "nlp" / "entity.py"
        
        if not entity_path.exists():
            pytest.skip(f"entity.py not found at {entity_path}")
        
        violations: List[str] = []
        
        class _Checker(ast.NodeVisitor):
            def __init__(self):
                self.in_feature_function = False
                self.function_name = ""
                self.function_lineno = 0
            
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                # Track if we're inside a feature-building function
                # (any function with "feature" in name or _token_features specifically)
                is_feature_fn = (
                    "feature" in node.name.lower()
                    or node.name == "_token_features"
                )
                
                if is_feature_fn:
                    old_in_feature = self.in_feature_function
                    old_name = self.function_name
                    old_lineno = self.function_lineno
                    
                    self.in_feature_function = True
                    self.function_name = node.name
                    self.function_lineno = node.lineno
                    
                    self.generic_visit(node)
                    
                    self.in_feature_function = old_in_feature
                    self.function_name = old_name
                    self.function_lineno = old_lineno
                else:
                    self.generic_visit(node)
            
            def visit_Call(self, node: ast.Call) -> None:
                # Check for dict(...) calls inside feature functions
                if self.in_feature_function:
                    if isinstance(node.func, ast.Name) and node.func.id == "dict":
                        violations.append(
                            f"{entity_path.name}:{node.lineno}: dict(...) literal in "
                            f"CRF feature function {self.function_name!r} (line {self.function_lineno}) — "
                            f"violates §10.21.1 CRF determinism (use list[tuple[str, float]] instead)"
                        )
                self.generic_visit(node)
            
            def visit_Dict(self, node: ast.Dict) -> None:
                # Check for {...} dict literals inside feature functions
                if self.in_feature_function:
                    violations.append(
                        f"{entity_path.name}:{node.lineno}: dict literal {{...}} in "
                        f"CRF feature function {self.function_name!r} (line {self.function_lineno}) — "
                        f"violates §10.21.1 CRF determinism (use list[tuple[str, float]] instead)"
                    )
                self.generic_visit(node)
        
        try:
            source = entity_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(entity_path))
            _Checker().visit(tree)
        except SyntaxError as exc:
            pytest.fail(f"Syntax error parsing {entity_path}: {exc}")
        
        assert violations == [], (
            "CRF feature builders have dict literals (violates §10.21.1 "
            "determinism guarantee):\n" + "\n".join(violations)
        )
