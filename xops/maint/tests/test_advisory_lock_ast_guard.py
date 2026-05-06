"""Phase 8 §8.15.3 — AST-scan guard.

The advisory-lock contract is binding: every ``pg_advisory_lock`` /
``pg_try_advisory_lock`` / ``pg_advisory_unlock`` call MUST flow
through :class:`xops.maint.advisory_lock.BoundLock` so the key
registry is the single source of truth. A grep is the cheap
gatekeeper — this test runs at unit-test time so a raw call in any
new code lights up red before review.

Allowed locations:

* ``xops/maint/advisory_lock.py`` — the helper itself.
* ``xops/maint/tests/`` — these tests.
* ``migrations/*.sql`` — SQL files are out of scope for this guard
  (PG-side advisory locks in ad-hoc maintenance scripts are owned
  by the operator).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Strict pattern — matches the bare PG functions, not Python helpers
# named similarly. Word-boundary on both sides keeps false positives
# (e.g. a comment about ``pg_try_advisory_lock_helper``) noisy on
# purpose: if you write the literal SQL function name in a Python
# string literal, you almost certainly want BoundLock.
_PATTERN = re.compile(
    r"\bpg_(try_)?advisory_(xact_)?(un)?lock\b"
)

_ALLOWED_REL = (
    "xops/maint/advisory_lock.py",
    "xops/maint/advisory_lock_keys.py",
    "xops/maint/tests/",
    # The opsctl audit prune subcommand does the SQL itself but
    # routes through BoundLock; a future refactor may inline the
    # SELECT — until then we permit references in the helper module.
)


def _iter_python_files() -> list[Path]:
    skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules",
                 "build", "dist", ".mypy_cache", ".pytest_cache"}
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*.py"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if any(part in skip_dirs for part in p.parts):
            continue
        out.append(p)
    return out


def test_no_raw_pg_advisory_calls_outside_helper() -> None:
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(allowed) for allowed in _ALLOWED_REL):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _PATTERN.search(line):
                offenders.append((rel, lineno, line.strip()[:120]))
    assert not offenders, (
        "raw pg_advisory_*() call outside BoundLock helper — route "
        "through xops.maint.advisory_lock.BoundLock instead:\n  "
        + "\n  ".join(f"{p}:{ln}: {snip}" for p, ln, snip in offenders)
    )
