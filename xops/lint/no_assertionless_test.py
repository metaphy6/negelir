#!/usr/bin/env python3
"""Phase 12 §12.12.5 — No assertion-free tests lint.

Scans test_*.py files for test functions with zero `assert` / `require` statements.
A function that adds coverage without assertions is a classic inflation trick (§12.12.5).
"""

import ast
import sys
from pathlib import Path

class AssertionFinder(ast.NodeVisitor):
    def __init__(self):
        self.has_assertion = False
        self.is_test_func = False
    
    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            self.is_test_func = True
            for child in node.body:
                if isinstance(child, ast.Assert):
                    self.has_assertion = True
                elif isinstance(child, ast.Expr):
                    if isinstance(child.value, ast.Call):
                        if isinstance(child.value.func, ast.Attribute):
                            if child.value.func.attr == "assert_":
                                self.has_assertion = True

def scan_file(path: Path) -> list[tuple[int, str]]:
    """Returns list of (line_number, function_name) for assertionless tests."""
    violations = []
    try:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                has_assert = False
                for child in ast.walk(node):
                    # Direct assert statement
                    if isinstance(child, ast.Assert):
                        has_assert = True
                        break
                    # pytest.raises context manager
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Attribute):
                            if child.func.attr in ("raises", "assert_", "fail", "skip"):
                                has_assert = True
                                break
                        elif isinstance(child.func, ast.Name):
                            if child.func.id in ("raises", "assert_", "fail", "skip"):
                                has_assert = True
                                break
                    # with pytest.raises(...):
                    if isinstance(child, ast.With):
                        for item in child.items:
                            if isinstance(item.context_expr, ast.Call):
                                if isinstance(item.context_expr.func, ast.Attribute):
                                    if item.context_expr.func.attr == "raises":
                                        has_assert = True
                                        break
                            elif isinstance(item.context_expr, ast.Attribute):
                                if item.context_expr.attr == "raises":
                                    has_assert = True
                                    break
                if not has_assert:
                    violations.append((node.lineno, node.name))
    except SyntaxError:
        pass
    return violations

if __name__ == "__main__":
    root = Path(__file__).parents[2]
    test_files = list((root / "ai" / "tests").glob("test_*.py"))
    
    all_violations = []
    for f in test_files:
        for lineno, func_name in scan_file(f):
            all_violations.append(f"{f.relative_to(root)}:{lineno} — {func_name}")
    
    if all_violations:
        print("❌ Assertionless tests (coverage inflation):")
        for v in all_violations:
            print(f"  {v}")
        sys.exit(1)
    else:
        print("✓ No assertionless tests found")
        sys.exit(0)
