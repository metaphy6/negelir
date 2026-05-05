"""Phase 8 §8.1 — opsctl boundary AST scan.

The ops console MUST NOT import storage clients (psycopg, redis
mutators) or shell out to psql / redis-cli. The bus is the only
sanctioned write surface; storage agents own their tables. This
test walks every ``.py`` under ``xops/opsctl/`` (excluding the
test dir) and rejects forbidden imports + ``subprocess`` calls
referencing those tools.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

OPSCTL_ROOT = Path(__file__).resolve().parents[1]
THIS_TESTS_DIR = Path(__file__).resolve().parent

FORBIDDEN_IMPORT_PREFIXES = (
    "psycopg",
    "psycopg2",
    "redis",  # the redis-py mutator surface (XADD/HSET/etc.)
    "asyncpg",
    "sqlalchemy",
)
# These are allowed because they ARE the bus seam.
ALLOWED_OVERRIDES = {
    # ai.swarm.sdk.bus *uses* redis internally, but opsctl talks to
    # it through the Bus protocol. We allow the indirection.
    "ai.swarm.sdk.bus",
}

FORBIDDEN_SUBPROCESS_TARGETS = ("psql", "redis-cli")


def _iter_opsctl_py() -> list[Path]:
    out: list[Path] = []
    for p in OPSCTL_ROOT.rglob("*.py"):
        if THIS_TESTS_DIR in p.parents:
            continue
        out.append(p)
    return sorted(out)


class TestOpsctlBoundary(unittest.TestCase):
    def test_no_forbidden_imports(self) -> None:
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ALLOWED_OVERRIDES:
                            continue
                        if any(alias.name.split(".")[0] == p for p in FORBIDDEN_IMPORT_PREFIXES):
                            offenders.append((str(path.relative_to(OPSCTL_ROOT.parent)), alias.name))
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod in ALLOWED_OVERRIDES:
                        continue
                    if any(mod.split(".")[0] == p for p in FORBIDDEN_IMPORT_PREFIXES):
                        offenders.append((str(path.relative_to(OPSCTL_ROOT.parent)), mod))
        self.assertEqual(
            offenders, [],
            msg=(
                "xops/opsctl/ MUST NOT import storage-mutator modules; "
                "the bus is the only write surface. Offenders: " + repr(offenders)
            ),
        )

    def test_no_subprocess_psql_or_redis_cli(self) -> None:
        """Reject string-arg references to forbidden tools that appear
        inside Call nodes (subprocess.run, os.system, Popen, etc.).
        Docstrings, comments, and identifier names are NOT flagged."""
        offenders: list[tuple[str, str]] = []
        for path in _iter_opsctl_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # Collect every literal-string arg (positional + kw).
                literals: list[str] = []
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        literals.append(arg.value)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                literals.append(elt.value)
                for s in literals:
                    for tool in FORBIDDEN_SUBPROCESS_TARGETS:
                        # Whole-token match guarded by non-word chars
                        # to avoid false positives ('psqlite' etc).
                        if tool == s or s.startswith(tool + " ") or (" " + tool) in s:
                            offenders.append(
                                (str(path.relative_to(OPSCTL_ROOT.parent)), tool)
                            )
        self.assertEqual(
            offenders, [],
            msg=("xops/opsctl/ MUST NOT shell out to: " + repr(offenders)),
        )


if __name__ == "__main__":
    unittest.main()
