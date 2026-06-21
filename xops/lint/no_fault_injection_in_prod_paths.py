"""AST guard: forbid fault injection imports outside tests/ and xops/chaos/.

Phase 12 §12.4 production-safety gate: the FaultInjector seam is test-only and
must not be reachable in production code paths. This lint forbids importing
`ai.swarm.sdk.fault` (or `ai.swarm.sdk.FaultInjector`) except in:
  - ai/tests/
  - xops/chaos/
  - xops/lint/  (linters themselves)

Failure mode: any violation is reported as FAIL_SAFE_FAULT_INJECTION_PROD_PATH.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ALLOWED_PATHS = ("ai/tests/", "xops/chaos/", "xops/lint/")
FAULT_MODULES = ("swarm.sdk.fault", "swarm.sdk")


def check_file(fpath: Path) -> list[str]:
    """Check if fault injection is imported in a non-allowed path."""
    rel_path = fpath.relative_to(Path.cwd())
    
    # Only check Python files
    if fpath.suffix != ".py":
        return []

    # Allow if in test/chaos/lint paths
    if any(str(rel_path).startswith(p) for p in ALLOWED_PATHS):
        return []

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(fpath))
    except SyntaxError:
        return []

    issues = []

    for node in ast.walk(tree):
        # Check for: from swarm.sdk.fault import ...
        if isinstance(node, ast.ImportFrom):
            if node.module and any(node.module.startswith(m) for m in FAULT_MODULES):
                issues.append(
                    f"{fpath}:{node.lineno}:{node.col_offset}: "
                    f"Fault injection (ai.swarm.sdk.fault) forbidden outside {ALLOWED_PATHS}; "
                    f"FAIL_SAFE_FAULT_INJECTION_PROD_PATH"
                )

        # Check for: import swarm.sdk as swarm
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name.startswith(m) for m in FAULT_MODULES):
                    issues.append(
                        f"{fpath}:{node.lineno}:{node.col_offset}: "
                        f"Fault injection (ai.swarm.sdk.fault) forbidden outside {ALLOWED_PATHS}; "
                        f"FAIL_SAFE_FAULT_INJECTION_PROD_PATH"
                    )

    return issues


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python no_fault_injection_in_prod_paths.py <file1.py> [file2.py ...]", file=sys.stderr)
        sys.exit(1)

    all_issues = []
    for arg in sys.argv[1:]:
        fpath = Path(arg)
        if fpath.is_file():
            all_issues.extend(check_file(fpath))
        elif fpath.is_dir():
            for py_file in fpath.rglob("*.py"):
                all_issues.extend(check_file(py_file))

    if all_issues:
        for issue in all_issues:
            print(issue)
        sys.exit(1)

    sys.exit(0)
