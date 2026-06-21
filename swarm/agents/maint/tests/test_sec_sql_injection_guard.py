"""Phase 8 §8.7 — SQL-injection guard for the maint.sec.v1 driver.

ROADMAP §8.7 binding: "All inserts/queries use parameterized
statements (`psycopg.sql.Composed`, never f-string concat).
Boundary test: AST scan of `ai/swarm/agents/maint/sec.py` rejects
``cursor.execute(f"...")`` and ``"%s" %`` patterns inside SQL
builders. The hit_substring is **never** placed in a SQL ``LIKE``
or ``=`` clause — only the fingerprint hash is."

This test is a boundary scan against ``ai/swarm/agents/maint/`` —
any new Postgres driver landing under §8.7b inherits the same
guard. Failure surfaces a precise file:line so the offending
construct can be replaced with parameterized SQL.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Iterator

# Files under maint/ that may legitimately build SQL strings. v1
# ships only the in-memory shims; the §8.7b Postgres driver lands
# in this directory and is the primary target of the scan.
_MAINT_DIR = pathlib.Path(__file__).resolve().parents[1]


def _python_files() -> Iterator[pathlib.Path]:
    for p in _MAINT_DIR.rglob("*.py"):
        # Skip the test directory itself — adversarial-pattern test
        # files legitimately contain the patterns we are scanning for.
        if "tests" in p.parts:
            continue
        yield p


def _looks_like_sql(s: str) -> bool:
    """Heuristic: a string is SQL-shaped if it **starts** with a
    canonical DML/DDL keyword (after leading whitespace). This is
    intentionally narrow so log/error messages that merely mention
    the word "from" or "into" do not trip the scan."""
    stripped = s.lstrip().lower()
    return any(stripped.startswith(kw) for kw in (
        "select ", "insert ", "update ", "delete ",
        "create ", "alter ", "drop ", "with ",
        "merge ", "truncate ", "values ",
    ))


def _bad_fstring_sql(node: ast.JoinedStr) -> bool:
    """Return True if a JoinedStr (an f-string) contains SQL-shaped
    literal text AND any FormattedValue (i.e. an interpolation)."""
    has_interp = any(isinstance(v, ast.FormattedValue) for v in node.values)
    if not has_interp:
        return False
    literal = "".join(
        v.value for v in node.values if isinstance(v, ast.Constant)
        and isinstance(v.value, str)
    )
    return _looks_like_sql(literal)


def _bad_percent_sql(node: ast.BinOp) -> bool:
    """Return True if a `% ` BinOp's left operand is a SQL-shaped
    string literal (the classic ``"INSERT ... %s" % (val,)`` shape).
    """
    if not isinstance(node.op, ast.Mod):
        return False
    left = node.left
    if isinstance(left, ast.Constant) and isinstance(left.value, str):
        return _looks_like_sql(left.value)
    return False


def _scan_file(path: pathlib.Path) -> list[str]:
    """Return a list of human-readable violation strings for the file
    (one per offending node). Empty list = clean."""
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover — fail loud
        return [f"{path}:{exc.lineno}: parse error: {exc.msg}"]
    rel = path.relative_to(_MAINT_DIR.parents[2])  # ai/swarm/agents/...
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and _bad_fstring_sql(node):
            violations.append(
                f"{rel}:{node.lineno}: f-string SQL with interpolation "
                "(use parameterized statements / psycopg.sql.Composed)"
            )
        elif isinstance(node, ast.BinOp) and _bad_percent_sql(node):
            violations.append(
                f"{rel}:{node.lineno}: '%' SQL formatting "
                "(use parameterized statements)"
            )
    return violations


def test_no_unsafe_sql_construction_under_maint() -> None:
    """ROADMAP §8.7 boundary: no f-string SQL with interpolation,
    no ``"...%s..." %`` percent-formatted SQL anywhere under
    ``ai/swarm/agents/maint/``."""
    all_violations: list[str] = []
    for p in _python_files():
        all_violations.extend(_scan_file(p))
    assert all_violations == [], (
        "SQL-injection guard tripped:\n  " + "\n  ".join(all_violations)
    )


def test_scanner_catches_fstring_sql_seed() -> None:
    """Self-test: the scanner itself must catch a known-bad pattern.
    Synthesises a small Python source string in memory (not on
    disk) so the production scan stays clean."""
    src = (
        "def bad(table):\n"
        "    cursor.execute(f\"SELECT * FROM {table} WHERE x = 1\")\n"
    )
    tree = ast.parse(src)
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.JoinedStr) and _bad_fstring_sql(n)]
    assert len(found) == 1


def test_scanner_catches_percent_sql_seed() -> None:
    """Self-test: percent-formatted SQL is also detected."""
    src = (
        "def bad(val):\n"
        "    cursor.execute('INSERT INTO t VALUES (%s)' % (val,))\n"
    )
    tree = ast.parse(src)
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.BinOp) and _bad_percent_sql(n)]
    assert len(found) == 1
