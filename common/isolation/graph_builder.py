"""Phase 18.1 §18.1 — Import graph builder and snapshot generator.

Scans all Python components (ai, common, datasource, swarm) and builds
a complete import graph. Exports to JSON format for snapshot checking.
Ledger #16, #30: supports regeneration via `make isolation.snapshot.refresh`.
"""

import ast
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class ImportGraphBuilder:
    """Builds import graph by scanning Python files."""

    def __init__(self, repo_root: Path):
        """Initialize builder with repo root."""
        self.repo_root = repo_root
        self.components = ["ai", "common"]  # Transitional layout (Phase 22 will have datasource/swarm)
        self.imports: Dict[str, List[Dict[str, Any]]] = {}
        self.violations: List[Dict[str, Any]] = []

    def build(self) -> Dict[str, Any]:
        """Scan all components and build import graph snapshot."""
        for component in self.components:
            comp_path = self.repo_root / component
            if comp_path.exists():
                self._scan_component(component, comp_path)

        return {
            "version": "18.1",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "components": self.components,
            "imports": self.imports,
            "violations": self.violations,
        }

    def _scan_component(self, component: str, comp_path: Path) -> None:
        """Recursively scan component for Python files and extract imports."""
        self.imports[component] = []

        for py_file in comp_path.rglob("*.py"):
            # Skip test files for now (Phase 18.2 will extend coverage)
            if "test" in py_file.name or "__pycache__" in py_file.parts:
                continue

            self._extract_imports(component, py_file)

    def _extract_imports(self, component: str, py_file: Path) -> None:
        """Extract import statements from a Python file."""
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            # Skip files that cannot be parsed
            return

        rel_path = str(py_file.relative_to(self.repo_root))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[component].append(
                        {
                            "file": rel_path,
                            "line": node.lineno,
                            "type": "import",
                            "module": alias.name,
                        }
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    self.imports[component].append(
                        {
                            "file": rel_path,
                            "line": node.lineno,
                            "type": "from",
                            "module": module,
                            "name": alias.name,
                        }
                    )


def generate_snapshot(repo_root: Path = None) -> Dict[str, Any]:
    """Generate import graph snapshot for the entire repo.

    Args:
        repo_root: Path to repository root. If None, discovered automatically.

    Returns:
        Dictionary representing the snapshot in JSON-serializable format.
    """
    if repo_root is None:
        # Walk up from cwd to find ROADMAP.md
        cwd = Path.cwd()
        while cwd != cwd.parent:
            if (cwd / "docs" / "planning" / "ROADMAP.md").exists():
                repo_root = cwd
                break
            cwd = cwd.parent
        if repo_root is None:
            raise RuntimeError("Could not find repo root (no ROADMAP.md found)")

    builder = ImportGraphBuilder(repo_root)
    return builder.build()


if __name__ == "__main__":
    import sys

    try:
        repo_root = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        snapshot = generate_snapshot(repo_root)
        print(json.dumps(snapshot, indent=2))
    except Exception as e:
        print(f"Error generating snapshot: {e}", file=sys.stderr)
        sys.exit(1)
