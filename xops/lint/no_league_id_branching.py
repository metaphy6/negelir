"""Phase 19 §19.2 — Python AST pluggability gate.

Asserts zero `if league_id == '...'` or `league_id in [...]` literals in
ai/**/*.py. This gate is re-asserted in Phase 19 after catalog additions.

Ledger #3 in ROADMAP Phase 19 identified five gap surfaces for pluggability.
This gate covers the Python AST verification.
"""

from __future__ import annotations

import sys
import ast
from pathlib import Path


class LeagueIdLiteralFinder(ast.NodeVisitor):
    """Find literal league_id comparisons in AST."""
    
    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []
    
    def visit_Compare(self, node: ast.Compare) -> None:
        """Check for league_id == 'literal' patterns."""
        # Check if left side is league_id
        if isinstance(node.left, ast.Name) and node.left.id == "league_id":
            for op, comparator in zip(node.ops, node.comparators):
                # Check for literal string comparisons
                if isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
                    if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                        self.violations.append((
                            node.lineno,
                            f"league_id {op.__class__.__name__} string literal"
                        ))
                    elif isinstance(comparator, ast.List):
                        # Check for league_id in [...]
                        for elt in comparator.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                self.violations.append((
                                    node.lineno,
                                    "league_id in [...] with string literals"
                                ))
                                break
        
        self.generic_visit(node)


def check_python_ast_pluggability(repo_root: Path) -> list[str]:
    """
    Scan ai/**/*.py for hardcoded league_id comparisons.
    
    Args:
        repo_root: Repository root
        
    Returns:
        List of error messages
    """
    errors = []
    
    ai_path = repo_root / "ai"
    if not ai_path.exists():
        return errors
    
    # Scan all Python files in ai/
    for py_file in ai_path.rglob("*.py"):
        # Skip test files and __pycache__
        if py_file.name.startswith("test_") or "__pycache__" in str(py_file):
            continue
        
        try:
            with open(py_file) as f:
                source = f.read()
            
            tree = ast.parse(source)
            finder = LeagueIdLiteralFinder()
            finder.visit(tree)
            
            if finder.violations:
                rel_path = py_file.relative_to(repo_root)
                for lineno, desc in finder.violations:
                    errors.append(
                        f"{rel_path}:{lineno}: ERROR: {desc}\n"
                        f"       League ID comparisons must use the pluggable catalog, not literals."
                    )
        except SyntaxError as e:
            # Skip files with syntax errors (they'll be caught elsewhere)
            pass
    
    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point for CI/CLI."""
    repo_root = Path(__file__).parent.parent.parent
    
    errors = check_python_ast_pluggability(repo_root)
    
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    
    print("✓ Python AST pluggability checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
