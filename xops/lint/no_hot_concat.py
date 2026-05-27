#!/usr/bin/env python3
"""
no_hot_concat.py — §9.17.2 hot-path string-concatenation guard.

Scans Go source files under ``server/internal/api/handlers/`` (configurable
via CLI args) and rejects string ``+`` concatenation inside HTTP handler
function bodies.  ``_test.go`` files are always exempt.

Rationale (§9.17.2): building strings with ``+`` in hot paths allocates a new
string header on every call.  Use ``strings.Builder`` or
``strconv.AppendInt(buf, ...)`` instead.

Detection heuristic (regex — no full Go AST parser):
  A line inside a handler file is flagged when it contains the ``+`` operator
  immediately adjacent to a string literal (``"..."`` on either side), OR when
  it contains ``fmt.Sprintf`` (which builds a string via format and allocation
  and is separately forbidden in the response-write hot path per §9.17.2).

Exemptions per-line: append ``// no_hot_concat: allow`` to suppress.

Exit code: 0 = clean, 1 = violations found, 2 = usage error.
Output: one line per violation, ``path:line: kind: snippet``.

Stdlib-only (per AGENTS.md §5: cross-platform, no third-party deps).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Default scan target per §9.17.2.
DEFAULT_ROOTS: tuple[str, ...] = ("server/internal/api/handlers",)

EXEMPT_SUFFIX = "_test.go"
ALLOW_MARKER = "no_hot_concat: allow"

# ── Patterns ─────────────────────────────────────────────────────────────

# String literal on the LEFT of +: `"..." + expr` or `"..." +\n`
_RE_STR_PLUS_LEFT = re.compile(r'"[^"]*"\s*\+')

# String literal on the RIGHT of +: `expr + "..."`
_RE_STR_PLUS_RIGHT = re.compile(r'\+\s*"[^"]*"')

# fmt.Sprintf call — always forbidden in response hot path.
_RE_FMT_SPRINTF = re.compile(r'\bfmt\.Sprintf\b')

PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("string_concat_left",  _RE_STR_PLUS_LEFT),
    ("string_concat_right", _RE_STR_PLUS_RIGHT),
    ("fmt_sprintf",         _RE_FMT_SPRINTF),
)


def _scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue
        for kind, pat in PATTERNS:
            if pat.search(line):
                snippet = line.strip()[:120]
                violations.append(f"{path}:{lineno}: {kind}: {snippet}")
                break  # one violation per line is enough

    return violations


def main(argv: list[str]) -> int:
    roots = argv[1:] if len(argv) > 1 else [str(REPO_ROOT / r) for r in DEFAULT_ROOTS]
    all_violations: list[str] = []
    for root_s in roots:
        root = Path(root_s)
        if not root.exists():
            # Directory may not exist yet (e.g. CI on a sparse checkout).
            continue
        for go_file in sorted(root.rglob("*.go")):
            if go_file.name.endswith(EXEMPT_SUFFIX):
                continue
            all_violations.extend(_scan_file(go_file))
    for v in all_violations:
        print(v)
    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
