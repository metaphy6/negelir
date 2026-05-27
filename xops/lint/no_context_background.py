#!/usr/bin/env python3
"""
no_context_background.py — §9.17.4 deadline-propagation guard.

Scans Go source files under ``server/internal/api/handlers/`` (configurable
via CLI args) and rejects calls to ``context.Background()`` or
``context.TODO()`` inside handler functions.

Rationale (§9.17.4): every outbound call in a handler MUST derive its
context from ``r.Context()`` so the request deadline is propagated to PG,
Redis, and bus calls. Using ``context.Background()`` or ``context.TODO()``
silently drops the deadline and can cause long-running goroutines that
outlive their request.

Detection heuristic (regex — no full Go AST parser):
  Any line in a non-test handler file containing ``context.Background()``
  or ``context.TODO()`` is flagged. To silence a justified exception (e.g.
  a shutdown-context that must outlive the request), append:
    // no_context_background: allow

Exemptions:
  * ``_test.go`` files are exempt.
  * Lines containing the allow marker are exempt.

Exit code: 0 = clean, 1 = violations found, 2 = usage error.
Output: one line per violation, ``path:line: kind: snippet``.

Stdlib-only (per AGENTS.md §5: cross-platform, no third-party deps).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Default scan target per §9.17.4.
DEFAULT_ROOTS: tuple[str, ...] = ("server/internal/api/handlers",)

EXEMPT_SUFFIX = "_test.go"
ALLOW_MARKER = "no_context_background: allow"

# ── Patterns ─────────────────────────────────────────────────────────────

_RE_BACKGROUND = re.compile(r'\bcontext\.Background\s*\(\s*\)')
_RE_TODO       = re.compile(r'\bcontext\.TODO\s*\(\s*\)')

PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("context_background", _RE_BACKGROUND),
    ("context_todo",       _RE_TODO),
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
                break  # one violation per line

    return violations


def main(argv: list[str]) -> int:
    roots = argv[1:] if len(argv) > 1 else [str(REPO_ROOT / r) for r in DEFAULT_ROOTS]
    all_violations: list[str] = []
    for root_s in roots:
        root = Path(root_s)
        if not root.exists():
            # Target directory may not exist in this phase; skip silently.
            continue
        for go_file in sorted(root.rglob("*.go")):
            if go_file.name.endswith(EXEMPT_SUFFIX):
                continue
            all_violations.extend(_scan_file(go_file))

    for v in all_violations:
        print(v)

    if all_violations:
        print(f"\nno_context_background: {len(all_violations)} violation(s) found.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
