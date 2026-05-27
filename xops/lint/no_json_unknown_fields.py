#!/usr/bin/env python3
"""
no_json_unknown_fields.py — §9.17.2 JSON decoder safety guard.

Scans Go source files under ``server/internal/api/handlers/`` (configurable
via CLI args) and asserts that every ``json.NewDecoder(`` call is followed by
a ``DisallowUnknownFields()`` invocation within the next
``LOOKAHEAD_LINES`` lines.

Rationale (§9.17.2 + defense-in-depth): ``DisallowUnknownFields()`` MUST be
set on every POST/PATCH handler decoder so that unexpected JSON keys are
rejected at the decode boundary rather than silently dropped.  This is a
second layer on top of the OpenAPI schema validator.

``_test.go`` files are always exempt.

Per-line exemption: append ``// no_json_unknown_fields: allow`` to the
``json.NewDecoder(`` line to suppress (e.g. for streaming / SSE decoders that
legitimately omit the check).

Exit code: 0 = clean, 1 = violations found, 2 = usage error.
Output: one line per violation, ``path:line: kind: snippet``.

Stdlib-only (per AGENTS.md §5: cross-platform, no third-party deps).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_ROOTS: tuple[str, ...] = ("server/internal/api/handlers",)

EXEMPT_SUFFIX = "_test.go"
ALLOW_MARKER = "no_json_unknown_fields: allow"

# How many lines after json.NewDecoder( to look for DisallowUnknownFields().
LOOKAHEAD_LINES = 6

_RE_NEW_DECODER = re.compile(r'\bjson\.NewDecoder\(')
_RE_DISALLOW    = re.compile(r'DisallowUnknownFields\(\)')


def _scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, start=1):
        if not _RE_NEW_DECODER.search(line):
            continue
        if ALLOW_MARKER in line:
            continue

        # Check whether DisallowUnknownFields() appears on the same line or
        # within the next LOOKAHEAD_LINES lines.
        window_start = lineno - 1  # 0-based
        window_end   = min(lineno - 1 + LOOKAHEAD_LINES + 1, len(lines))
        window       = lines[window_start:window_end]
        found = any(_RE_DISALLOW.search(ln) for ln in window)

        if not found:
            snippet = line.strip()[:120]
            violations.append(
                f"{path}:{lineno}: missing_disallow_unknown_fields: {snippet}"
            )

    return violations


def main(argv: list[str]) -> int:
    roots = argv[1:] if len(argv) > 1 else [str(REPO_ROOT / r) for r in DEFAULT_ROOTS]
    all_violations: list[str] = []
    for root_s in roots:
        root = Path(root_s)
        if not root.exists():
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
