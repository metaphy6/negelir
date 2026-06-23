#!/usr/bin/env python3
"""`make compose.*` — Docker Compose lifecycle and reporting (real implementations).

Targets:
    overlay.usage_report   Check for any references to deprecated mock overlay in the codebase
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err, ok, info  # noqa: E402


def cmd_overlay_usage_report(_argv: List[str]) -> int:
    """Check for any references to the deprecated mock overlay file in the codebase.
    
    Returns 0 if no references found (safe to remove), 1 if references exist.
    Excludes test files to avoid false positives from test fixtures and mocks.
    """
    hits: list[tuple[Path, int, str]] = []
    
    # Pattern to search for (avoids matching compose.py itself)
    pattern = "docker-compose.mock"
    
    # Directories to search (exclude .git, .venv, node_modules, etc.)
    ignore_dirs = {".git", ".venv", "venv", "node_modules", ".pytest_cache", ".coverage", "__pycache__", "tests"}
    
    # Files to exclude from search (to avoid false positives from the search tool itself)
    exclude_files = {"compose.py"}
    
    for py_file in REPO_ROOT.rglob("*.py"):
        # Skip ignored directories, test files, and self-references
        if any(part in ignore_dirs for part in py_file.parts) or py_file.name in exclude_files:
            continue
        # Also skip files in any path segment named 'tests' or test-like patterns
        if any(part.startswith("test_") or part == "tests" or part.endswith("_test.py") for part in py_file.parts):
            continue
        
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(content.split("\n"), 1):
                if pattern in line:
                    hits.append((py_file, line_no, line.strip()))
        except (OSError, ValueError):
            pass
    
    # Also check YAML and shell scripts
    for file in REPO_ROOT.rglob("*"):
        if file.is_dir() or any(part in ignore_dirs for part in file.parts):
            continue
        # Skip test files in all formats
        if any(part.startswith("test_") or part == "tests" or part.endswith("_test.yaml") or part.endswith("_test.yml") for part in file.parts):
            continue
        if file.suffix in {".yml", ".yaml", ".sh"}:
            try:
                content = file.read_text(encoding="utf-8", errors="ignore")
                for line_no, line in enumerate(content.split("\n"), 1):
                    if pattern in line:
                        hits.append((file, line_no, line.strip()))
            except (OSError, ValueError):
                pass
    
    if hits:
        err(f"Found {len(hits)} reference(s) to deprecated mock overlay:")
        for path, line_no, line in sorted(hits):
            rel_path = path.relative_to(REPO_ROOT)
            info(f"  {rel_path}:{line_no}: {line[:100]}")
        return 1
    
    ok("No references to deprecated mock overlay found — safe to remove.")
    return 0


COMMANDS = {
    "overlay.usage_report": cmd_overlay_usage_report,
}


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:], COMMANDS, script_name="compose.py"))
