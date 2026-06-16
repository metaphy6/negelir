#!/usr/bin/env python3
"""Phase 18.3 — Shim-only gate for ai/ directory deletion.

Parses every .py file under ai/ and enforces that each file is a
pure re-export shim of datasource.*, swarm.*, or common.* modules.

A shim is ONLY:
  - Module docstring
  - Comments
  - Imports from datasource.*, swarm.*, common.*
  - __all__ declaration
  - Blank lines

No real implementation (class definitions, function definitions,
variable assignments, etc.) is allowed.

Exit code:
  0 if all files are shim-only
  1 if any file contains real implementation
  2 if a parse error occurs
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = REPO_ROOT / "ai"


class ShimValidator(ast.NodeVisitor):
    """Validates that a module contains only shim re-exports."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.violations: list[tuple[int, str]] = []
        self.in_module_docstring = True
        self.seen_module_docstring = False

    def visit_Module(self, node: ast.Module) -> None:
        """Validate the module structure."""
        # Allow module docstring as the first statement
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(
            node.body[0].value, ast.Constant
        ):
            self.seen_module_docstring = True
            self.visit(node.body[0])
            # Continue with rest of module
            for stmt in node.body[1:]:
                self.visit(stmt)
        else:
            # No module docstring, visit all
            for stmt in node.body:
                self.visit(stmt)

    def visit_Expr(self, node: ast.Expr) -> None:
        """Allow only module docstrings (string constants at module level)."""
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            # This is OK (docstring) — don't record a violation
            pass
        else:
            self.violations.append((node.lineno, "Expression statement is not allowed in shim"))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Allow only imports from datasource.*, swarm.*, common.*."""
        if node.module is None:
            # Relative import with no name (e.g., `from . import x`)
            self.violations.append((node.lineno, "Relative imports are not allowed in shim"))
        elif not any(
            node.module.startswith(prefix)
            for prefix in ("datasource", "swarm", "common")
        ):
            self.violations.append(
                (node.lineno, f"Import from disallowed module: {node.module}")
            )

    def visit_Import(self, node: ast.Import) -> None:
        """Disallow absolute imports."""
        for alias in node.names:
            if not any(
                alias.name.startswith(prefix) for prefix in ("datasource", "swarm", "common")
            ):
                self.violations.append(
                    (node.lineno, f"Import of disallowed module: {alias.name}")
                )

    def visit_Assign(self, node: ast.Assign) -> None:
        """Allow only __all__ assignment."""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "__all__":
                # __all__ is OK, but should be a list literal
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    return
                else:
                    self.violations.append(
                        (node.lineno, "__all__ must be a list or tuple literal")
                    )
            else:
                self.violations.append(
                    (node.lineno, f"Variable assignment is not allowed in shim: {node.targets[0].id}")
                )
        else:
            self.violations.append((node.lineno, "Assignment is not allowed in shim"))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Disallow class definitions."""
        self.violations.append((node.lineno, f"Class definition not allowed in shim: {node.name}"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Disallow function definitions."""
        self.violations.append((node.lineno, f"Function definition not allowed in shim: {node.name}"))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Disallow async function definitions."""
        self.violations.append(
            (node.lineno, f"Async function definition not allowed in shim: {node.name}")
        )

    def visit_If(self, node: ast.If) -> None:
        """Disallow conditional logic."""
        self.violations.append((node.lineno, "Conditional logic is not allowed in shim"))

    def visit_For(self, node: ast.For) -> None:
        """Disallow loops."""
        self.violations.append((node.lineno, "Loop is not allowed in shim"))

    def visit_While(self, node: ast.While) -> None:
        """Disallow while loops."""
        self.violations.append((node.lineno, "While loop is not allowed in shim"))

    def visit_Try(self, node: ast.Try) -> None:
        """Disallow try/except."""
        self.violations.append((node.lineno, "Try/except is not allowed in shim"))

    def visit_With(self, node: ast.With) -> None:
        """Disallow context managers."""
        self.violations.append((node.lineno, "With statement is not allowed in shim"))

    def generic_visit(self, node: Any) -> None:
        """Continue visiting child nodes."""
        super().generic_visit(node)


def validate_file(file_path: Path) -> bool:
    """Validate a single Python file.
    
    Returns True if the file is a valid shim, False otherwise.
    Prints violations to stderr.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        print(f"SYNTAX_ERROR {file_path}:{e.lineno} {e.msg}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR {file_path}: {e}", file=sys.stderr)
        return False

    validator = ShimValidator(str(file_path))
    validator.visit(tree)

    if validator.violations:
        for lineno, msg in validator.violations:
            print(f"VIOLATION {file_path}:{lineno} {msg}", file=sys.stderr)
        return False

    return True


def main(argv: list[str]) -> int:
    """Main entry point.
    
    Scans ai/ and all its Python files, validating that each is a shim.
    
    Returns 0 if all files are valid shims, 1 if any contain real code,
    2 if parse errors occur.
    """
    # Find all Python files under ai/
    ai_py_files = list(AI_ROOT.glob("**/*.py"))

    if not ai_py_files:
        print(f"ERROR: No Python files found under {AI_ROOT}", file=sys.stderr)
        return 1

    has_violations = False
    has_errors = False

    for py_file in sorted(ai_py_files):
        if py_file.name == "__pycache__":
            continue
        if is_valid := validate_file(py_file):
            print(f"OK {py_file.relative_to(REPO_ROOT)}")
        else:
            has_violations = True

    if has_violations:
        print(
            f"\nFAILURE: {len(ai_py_files)} files scanned; some contain real implementation",
            file=sys.stderr,
        )
        return 1

    print(f"\nSUCCESS: All {len(ai_py_files)} files under ai/ are shim-only")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
