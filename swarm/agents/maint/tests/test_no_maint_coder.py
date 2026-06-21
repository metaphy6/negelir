"""Phase 8.9 DoD: maint.coder.v1 must not exist.

The auto-coder is Phase 17 patcher territory. This test acts as a
CI gate: it asserts the module is absent on disk AND that no file
in the workspace imports it via

    from swarm.agents.maint.coder import ...
    import swarm.agents.maint.coder

Any violation surfaces a precise file:line so the offending import
can be removed before merge.
"""
from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]
_MAINT_DIR = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. Module-absent check
# ---------------------------------------------------------------------------

def test_maint_coder_module_not_present() -> None:
    """No coder.py or coder/ package exists under maint/."""
    coder_py = _MAINT_DIR / "coder.py"
    coder_pkg = _MAINT_DIR / "coder"
    assert not coder_py.exists(), (
        f"maint/coder.py must not exist (Phase 17 scope): {coder_py}"
    )
    assert not coder_pkg.is_dir(), (
        f"maint/coder/ package must not exist (Phase 17 scope): {coder_pkg}"
    )


# ---------------------------------------------------------------------------
# 2. AST import-scan
# ---------------------------------------------------------------------------

def _python_files() -> list[pathlib.Path]:
    results: list[pathlib.Path] = []
    for root in (_REPO_ROOT / "ai", _REPO_ROOT / "xops"):
        if root.is_dir():
            results.extend(root.rglob("*.py"))
    return results


def _is_coder_import(node: ast.stmt) -> bool:
    """Return True if the AST node is a forbidden maint.coder import."""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return "swarm.agents.maint.coder" in module
    if isinstance(node, ast.Import):
        return any("swarm.agents.maint.coder" in alias.name for alias in node.names)
    return False


def test_no_import_of_maint_coder() -> None:
    """AST scan: no file imports swarm.agents.maint.coder."""
    violations: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if _is_coder_import(node):
                rel = path.relative_to(_REPO_ROOT)
                violations.append(f"{rel}:{node.lineno}")

    assert not violations, (
        "Phase 17 scope violation — 'swarm.agents.maint.coder' imported at:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
