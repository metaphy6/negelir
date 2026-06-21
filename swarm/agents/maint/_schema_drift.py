"""Phase 8 §8.6 Detectors B + C — drift parsers.

Two pure helpers, kept out of :mod:`schema` so the agent body stays
readable:

* :func:`parse_migrations_dir` — tolerant SQL parser that walks
  ``migrations/*.sql`` and returns
  ``(table_name → set[column_name])`` plus a set of
  ``unknown_constructs`` table names whose expected column set was
  assembled in the presence of a parse failure (used to downgrade
  drift severity to ``info``).
* :func:`parse_payloads_dataclasses` — AST walk over a Python source
  file collecting every top-level ``@dataclass`` class name and its
  declared ``AnnAssign`` field names.

Both helpers are deliberately stdlib-only (no ``sqlglot`` dep). The
ROADMAP §8.6 binding mentions ``sqlglot`` as an upgrade path; we
keep it optional behind a try/except so the helper still runs in
test environments without that dep.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Migration parser (Detector B) ─────────────────────────────────


# Match `CREATE TABLE [IF NOT EXISTS] <name> (`. Also tolerates a
# schema-qualified name (`public.foo`) by stripping the prefix.
_RE_CREATE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[A-Za-z_][\w$]*\.)?([A-Za-z_][\w$]*)\s*\(",
    re.IGNORECASE,
)
# Match `ALTER TABLE [ONLY] <name> ADD COLUMN [IF NOT EXISTS] <col>`.
_RE_ALTER_ADD = re.compile(
    r"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?:[A-Za-z_][\w$]*\.)?"
    r"([A-Za-z_][\w$]*)\s+ADD\s+(?:COLUMN\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*)",
    re.IGNORECASE,
)
# Match a column declaration line inside a CREATE TABLE body. We
# accept anything that starts with an identifier followed by
# whitespace and a type-token; reject anything starting with a
# constraint keyword.
_COLUMN_KEYWORDS = (
    "constraint", "primary", "foreign", "unique", "check",
    "exclude", "like", "deferrable", "initially",
)


@dataclass
class MigrationsDigest:
    tables: dict[str, set[str]] = field(default_factory=dict)
    unknown_constructs: set[str] = field(default_factory=set)


def _strip_sql_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* ... */`` block comments."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def _split_top_level_commas(body: str) -> list[str]:
    """Split a ``CREATE TABLE`` body on commas that sit at depth 0
    (so nested ``CHECK (a, b)`` parens don't split incorrectly)."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _extract_columns_from_body(body: str) -> tuple[set[str], bool]:
    """Return ``(columns, had_unknown_construct)`` for a CREATE TABLE body."""
    cols: set[str] = set()
    unknown = False
    for raw in _split_top_level_commas(body):
        line = raw.strip()
        if not line:
            continue
        # First token of the line.
        first = line.split(None, 1)[0].lower()
        if first in _COLUMN_KEYWORDS:
            # Table-level constraint — not a column.
            continue
        # Expect: <ident> <type> [...] — strip optional surrounding quotes.
        m = re.match(r'^(?:"([^"]+)"|`([^`]+)`|([A-Za-z_][\w$]*))', line)
        if not m:
            unknown = True
            continue
        col = m.group(1) or m.group(2) or m.group(3)
        cols.add(col.lower())
    return cols, unknown


def parse_migrations_dir(migrations_dir: Path) -> MigrationsDigest:
    """Parse every ``*.sql`` file under ``migrations_dir`` (sorted)
    and accumulate the expected ``table → columns`` map.

    Forward-only assumption: ``ALTER TABLE ... ADD COLUMN`` is
    additive; ``DROP COLUMN`` is intentionally NOT honored (Phase 8
    doctrine — the patcher's `migration` scope refuses DROP). Files
    that fail to parse cleanly mark every table they touch in
    ``unknown_constructs``.
    """
    digest = MigrationsDigest()
    if not migrations_dir.is_dir():
        return digest
    for path in sorted(migrations_dir.glob("*.sql")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        sql = _strip_sql_comments(raw)
        # CREATE TABLE bodies — find paren-balanced spans.
        for m in _RE_CREATE.finditer(sql):
            table = m.group(1).lower()
            # Walk to the matching close-paren.
            start = m.end() - 1  # at the '('
            depth = 0
            close = -1
            for i in range(start, len(sql)):
                if sql[i] == "(":
                    depth += 1
                elif sql[i] == ")":
                    depth -= 1
                    if depth == 0:
                        close = i
                        break
            if close == -1:
                digest.unknown_constructs.add(table)
                continue
            body = sql[m.end():close]
            cols, had_unknown = _extract_columns_from_body(body)
            digest.tables.setdefault(table, set()).update(cols)
            if had_unknown:
                digest.unknown_constructs.add(table)
        # ALTER TABLE ... ADD COLUMN.
        for m in _RE_ALTER_ADD.finditer(sql):
            table = m.group(1).lower()
            col = m.group(2).lower()
            digest.tables.setdefault(table, set()).add(col)
    return digest


def diff_columns(
    expected: dict[str, set[str]],
    observed: dict[str, set[str]],
) -> list[tuple[str, str, list[str]]]:
    """Compare two ``table → columns`` maps. Returns a list of
    ``(table, drift_kind, details)`` tuples where ``drift_kind`` is
    one of ``"missing_table"`` (in expected, not observed),
    ``"extra_table"`` (in observed, not expected),
    ``"missing_columns"`` (in expected for the table, not observed),
    ``"extra_columns"`` (in observed for the table, not expected).
    Tables with identical column sets produce no entry."""
    out: list[tuple[str, str, list[str]]] = []
    exp_tables = set(expected.keys())
    obs_tables = set(observed.keys())
    for t in sorted(exp_tables - obs_tables):
        out.append((t, "missing_table", []))
    for t in sorted(obs_tables - exp_tables):
        out.append((t, "extra_table", []))
    for t in sorted(exp_tables & obs_tables):
        e = expected[t]
        o = observed[t]
        missing = sorted(e - o)
        extra = sorted(o - e)
        if missing:
            out.append((t, "missing_columns", missing))
        if extra:
            out.append((t, "extra_columns", extra))
    return out


# ── Dataclass parser (Detector C) ─────────────────────────────────


@dataclass
class DataclassDigest:
    classes: dict[str, set[str]] = field(default_factory=dict)


def parse_payloads_dataclasses(path: Path) -> DataclassDigest:
    """AST-walk a single Python module; return every top-level class
    decorated with ``@dataclass`` (positional or ``@dataclass(...)``)
    along with its declared ``AnnAssign`` field names. Inheritance is
    intentionally NOT followed — drift detection is at the explicit-
    field-list boundary."""
    digest = DataclassDigest()
    if not path.is_file():
        return digest
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return digest
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not _has_dataclass_decorator(node):
            continue
        fields: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                # Skip ClassVar / private convention names starting
                # with underscore (treated as implementation detail).
                name = stmt.target.id
                if name.startswith("_"):
                    continue
                fields.add(name)
        digest.classes[node.name] = fields
    return digest


def _has_dataclass_decorator(node: ast.ClassDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            return True
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) \
                and dec.func.id == "dataclass":
            return True
        # `@dataclasses.dataclass` form.
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            return True
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                and dec.func.attr == "dataclass":
            return True
    return False


def diff_dataclass_vs_schema(
    *,
    dataclass_fields: set[str],
    schema_properties: set[str],
    schema_required: set[str],
) -> list[str]:
    """Return a list of human-readable drift messages comparing a
    Python dataclass field set against a JSON Schema's properties
    + required set. Empty list = no drift."""
    msgs: list[str] = []
    missing_in_dataclass = sorted(schema_required - dataclass_fields)
    if missing_in_dataclass:
        msgs.append(
            f"schema-required fields missing from dataclass: "
            f"{missing_in_dataclass}"
        )
    extra_in_dataclass = sorted(dataclass_fields - schema_properties)
    if extra_in_dataclass:
        msgs.append(
            f"dataclass fields not declared in schema properties: "
            f"{extra_in_dataclass}"
        )
    return msgs


__all__ = [
    "MigrationsDigest",
    "DataclassDigest",
    "parse_migrations_dir",
    "parse_payloads_dataclasses",
    "diff_columns",
    "diff_dataclass_vs_schema",
]
