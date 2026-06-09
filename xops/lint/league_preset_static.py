"""Phase 13.3.4 lint: Refuse computed values and aliases in LeagueConfig presets.

League presets must contain only static data: team rosters, format parameters,
derby pairs, etc. Never computed values (os.environ, function calls, list
comprehensions, database lookups at import time, etc.) and never team-name
aliases (which belong in Team records, not presets).

Violation patterns:
- os.environ[...]
- os.getenv(...)
- function_call(...)
- [... for x in ...]  (list comprehension)
- {... for x in ...}  (set/dict comprehension)
- aliases=[...]  (team aliases belong in Team records, not presets)
"""

import ast
import re
from pathlib import Path


class ComputedValueDetector(ast.NodeVisitor):
    """AST visitor that detects computed values in preset files."""

    def __init__(self, preset_path: str):
        self.preset_path = preset_path
        self.violations = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Detect os.environ, os.getenv, etc."""
        if isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr in ("environ", "getenv"):
                self.violations.append(
                    f"Line {node.lineno}: os.{node.attr} is computed (must be static)"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Detect function calls (e.g., function_name(...))."""
        # Allow specific safe calls: frozenset, dict, list, set, LeagueConfig, etc.
        safe_builtins = {"frozenset", "dict", "list", "set", "tuple", "LeagueConfig"}

        if isinstance(node.func, ast.Name):
            if node.func.id not in safe_builtins:
                self.violations.append(
                    f"Line {node.lineno}: Function call {node.func.id}() is computed"
                )
        elif isinstance(node.func, ast.Attribute):
            # Also flag module.function() calls (except type-related ones)
            if isinstance(node.func.value, ast.Name):
                # Allow some safe attribute calls like frozenset([...])
                if node.func.value.id not in ("", "builtins"):
                    self.violations.append(
                        f"Line {node.lineno}: Method call is computed (must be static)"
                    )

        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        """Detect list comprehensions."""
        self.violations.append(
            f"Line {node.lineno}: List comprehension is computed (must be static)"
        )
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        """Detect set comprehensions."""
        self.violations.append(
            f"Line {node.lineno}: Set comprehension is computed (must be static)"
        )
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Detect dict comprehensions."""
        self.violations.append(
            f"Line {node.lineno}: Dict comprehension is computed (must be static)"
        )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Detect non-empty aliases assignments.
        
        Team-name aliases belong in Team records (Reference plane), not in presets.
        This prevents duplication and maintains the preset discipline.
        """
        # Check if any target is named 'aliases'
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "aliases":
                # Check if the value is a non-empty list, set, or frozenset
                if self._has_non_empty_collection(node.value):
                    self.violations.append(
                        f"Line {node.lineno}: aliases with non-empty value found "
                        "(aliases belong in Team records, not presets)"
                    )
                break

        self.generic_visit(node)

    def _has_non_empty_collection(self, node: ast.expr) -> bool:
        """Check if a node represents a non-empty list, set, or frozenset.
        
        Returns True if the collection is provably non-empty, False otherwise.
        """
        if isinstance(node, ast.List):
            # List literal: [...] is non-empty if it has elements
            return len(node.elts) > 0
        elif isinstance(node, ast.Set):
            # Set literal: {...} is non-empty if it has elements
            return len(node.elts) > 0
        elif isinstance(node, ast.Call):
            # frozenset([...]) or list([...]) or set([...])
            if isinstance(node.func, ast.Name):
                if node.func.id in ("frozenset", "set", "list"):
                    # Check if there's an argument and it's non-empty
                    if node.args and isinstance(node.args[0], ast.List):
                        return len(node.args[0].elts) > 0
        
        return False



def lint_preset_file(preset_path: str) -> list[str]:
    """Lint a single preset file for computed values.

    Args:
        preset_path: Path to the preset .py file

    Returns:
        List of violation messages, or empty list if clean
    """
    try:
        with open(preset_path, "r") as f:
            source = f.read()

        tree = ast.parse(source, filename=preset_path)
    except SyntaxError as e:
        return [f"Syntax error: {e}"]
    except Exception as e:
        return [f"Failed to parse: {e}"]

    detector = ComputedValueDetector(preset_path)
    detector.visit(tree)

    return detector.violations


def lint_all_presets(leagues_dir: Path = None) -> dict:
    """Lint all preset files in ai/common/leagues/.

    Args:
        leagues_dir: Path to leagues directory (default: ai/common/leagues)

    Returns:
        {preset_file: [violations]} dict; empty if all clean
    """
    if leagues_dir is None:
        leagues_dir = Path(__file__).parent.parent.parent / "common" / "leagues"

    results = {}

    for preset_file in sorted(leagues_dir.glob("*.py")):
        if preset_file.name in ("__init__.py", "__pycache__"):
            continue

        violations = lint_preset_file(str(preset_file))
        if violations:
            results[preset_file.name] = violations

    return results


if __name__ == "__main__":
    import sys
    import json

    leagues_dir = Path(__file__).parent.parent.parent / "common" / "leagues"
    results = lint_all_presets(leagues_dir)

    if results:
        print(f"❌ {len(results)} preset file(s) have violations:")
        for preset_file, violations in results.items():
            print(f"\n  {preset_file}:")
            for violation in violations:
                print(f"    - {violation}")
        sys.exit(1)
    else:
        print("✅ All presets pass structural-only lint")
        sys.exit(0)
