"""ROADMAP §8.12 — boundary discipline tests.

Two concerns:

1. **AST import scan** — every ``.py`` file under ``xops/backup/offsite/``
   must carry no imports from ``swarm.*``, ``psycopg``, or
   ``redis.client.*``.  The offsite package is a pure replicator (disk →
   remote → bus); it must never reach into database or cache mutators.

2. **secret_smoke unit tests** — verify that :func:`check_output` correctly
   flags real-looking credential patterns and ignores the short fake keys
   ("ak", "sk") used throughout the test suite.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from xops.backup.secret_smoke import check_output

# ---------------------------------------------------------------------------
# AST scan helpers
# ---------------------------------------------------------------------------

_OFFSITE_ROOT = Path(__file__).resolve().parent.parent / "offsite"

# Top-level module roots that are forbidden inside xops/backup/offsite/.
_FORBIDDEN_ROOTS: frozenset[str] = frozenset({"swarm", "psycopg"})

# Dotted module paths forbidden as prefixes (covers redis.client and sub-modules).
_FORBIDDEN_PREFIXES: tuple[str, ...] = ("redis.client",)


def _check_node(node: ast.Import | ast.ImportFrom) -> str | None:
    """Return a human-readable description if *node* imports from a forbidden module.

    Returns ``None`` when the import is permitted.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _FORBIDDEN_ROOTS:
                return f"import {alias.name}"
            if any(alias.name == p or alias.name.startswith(p + ".") for p in _FORBIDDEN_PREFIXES):
                return f"import {alias.name}"
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        root = module.split(".")[0]
        if root in _FORBIDDEN_ROOTS:
            return f"from {module} import ..."
        if any(module == p or module.startswith(p + ".") for p in _FORBIDDEN_PREFIXES):
            return f"from {module} import ..."
    return None


def _collect_py_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".py"):
                files.append(Path(dirpath) / name)
    return sorted(files)


_OFFSITE_PY_FILES = _collect_py_files(_OFFSITE_ROOT)


# ---------------------------------------------------------------------------
# Parametrized AST scan — one test per source file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("py_file", _OFFSITE_PY_FILES, ids=[str(p.name) for p in _OFFSITE_PY_FILES])
def test_offsite_no_forbidden_imports(py_file: Path) -> None:
    """``xops/backup/offsite/*.py`` must not import swarm.*, psycopg, or redis.client.*."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            desc = _check_node(node)
            if desc:
                violations.append(f"line {node.lineno}: {desc}")
    rel = py_file.relative_to(_OFFSITE_ROOT.parent)
    assert not violations, (
        f"offsite/{rel} contains forbidden import(s):\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# secret_smoke unit tests
# ---------------------------------------------------------------------------


def test_secret_smoke_detects_aws_key_id() -> None:
    """A real-format AWS access key ID must be flagged."""
    text = (
        "INFO starting upload\n"
        "WARNING access_key=AKIAIOSFODNN7EXAMPLE replicated\n"
    )
    hits = check_output(text)
    assert any(name == "aws_key_id" for _, name, _ in hits), (
        "Expected aws_key_id pattern to fire on AKIA... string"
    )


def test_secret_smoke_detects_kv_secret() -> None:
    """A long ``secret=<value>`` pattern must be flagged."""
    text = "ERROR failed to connect secret=MyRealLongSecretValue123\n"
    hits = check_output(text)
    assert any(name == "kv_secret" for _, name, _ in hits), (
        "Expected kv_secret pattern to fire"
    )


def test_secret_smoke_detects_bearer_token() -> None:
    """An Authorization: Bearer header with a long token must be flagged."""
    text = "DEBUG outbound header Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9\n"
    hits = check_output(text)
    assert any(name == "bearer_token" for _, name, _ in hits), (
        "Expected bearer_token pattern to fire"
    )


def test_secret_smoke_ignores_short_fake_keys() -> None:
    """Short unit-test placeholders (\"ak\", \"sk\") must NOT be flagged."""
    text = (
        'DEBUG s3 init endpoint=http://s3.local:9000 '
        'access_key_id="ak" secret_access_key="sk"\n'
    )
    hits = check_output(text)
    assert not hits, f"Unexpected hits on short fake keys: {hits}"


def test_secret_smoke_clean_log_passes() -> None:
    """Benign log output must produce no hits."""
    text = (
        "INFO upload started bucket=backups key=2025-01-01/dump.sql.gz\n"
        "INFO upload complete size_bytes=104857600 duration_s=12.3\n"
        "INFO offsite age hours=2.1\n"
    )
    hits = check_output(text)
    assert not hits, f"Unexpected hits on clean text: {hits}"


def test_secret_smoke_empty_text_passes() -> None:
    """Empty string returns no hits."""
    assert check_output("") == []


def test_secret_smoke_fake_prefix_bypasses_aws_secret() -> None:
    """A 40-char string prefixed with 'FAKE_' must be skipped."""
    fake = "FAKE_" + "A" * 40
    hits = check_output(f"DEBUG key={fake}\n")
    assert not any(name == "aws_secret" for _, name, _ in hits), (
        "FAKE_ prefix should suppress aws_secret pattern"
    )
