#!/usr/bin/env python3
"""
no_unconditional_string_translate.py — §10.34.2 zero-copy guarantee guard.

Scans Python source files under ``ai/nlp/normalize*`` and related normalize 
modules and forbids bare ``.translate(...)`` and ``.join(...)`` calls 
without a preceding ``if changed(s)`` check.

Rationale (§10.34.2): normalize passes must guarantee zero-copy when no action 
is needed (return `s is input`, not a copy). Calls to `.translate()` or 
`.join()` always allocate, even on no-op transformations.

Detection heuristic (regex):
  A line is flagged when it contains:
  - Bare ``.translate(`` NOT preceded by an ``if changed`` check, OR
  - Bare ``.join(`` NOT preceded by an ``if changed`` check

Exemptions per-line: append ``# no_unconditional_string_translate: allow`` 
to suppress.

Exit code: 0 = clean, 1 = violations found, 2 = usage error.
Output: one line per violation, ``path:line: kind: snippet``.

Stdlib-only (per AGENTS.md §5: cross-platform, no third-party deps).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

# Default scan target per §10.34.2 — normalize modules.
DEFAULT_ROOTS: tuple[str, ...] = (
    "ai/nlp/normalize.py",
    "ai/swarm/agents/nlp/normalize",
    "ai/common/text",
)

EXEMPT_SUFFIX_FILE = "_test.py"
ALLOW_MARKER = "no_unconditional_string_translate: allow"

# ── Patterns ─────────────────────────────────────────────────────────────

# Bare `.translate(` — flag unless preceded by `if changed`
# Look for `.translate(` on a line that does NOT start with `if changed`
_RE_BARE_TRANSLATE = re.compile(r"\.translate\s*\(")

# Bare `.join(` — flag unless preceded by `if changed`
# Look for `.join(` on a line that does NOT start with `if changed`
_RE_BARE_JOIN = re.compile(r"\.join\s*\(")

# Preceding guard: `if changed(` or `if.*changed(` on same or prior context
# Match common guard patterns like `if changed(`, `if _has_punct_to_normalize(`, etc.
_RE_GUARD = re.compile(r"\bif\s+.*\b(?:changed|_has_\w+)\s*\(")


def _has_guard(line: str) -> bool:
    """Check if the line has a preceding `if changed(...)` guard."""
    # Simple heuristic: if the line contains `if changed(` before any `.translate` or `.join`,
    # it is guarded.
    match_guard = _RE_GUARD.search(line)
    match_translate = _RE_BARE_TRANSLATE.search(line)
    match_join = _RE_BARE_JOIN.search(line)

    # If no translate/join, no problem
    if not match_translate and not match_join:
        return True

    # If there is a guard, check it comes before the translate/join
    if match_guard:
        guard_pos = match_guard.start()
        translate_pos = match_translate.start() if match_translate else float('inf')
        join_pos = match_join.start() if match_join else float('inf')
        problem_pos = min(translate_pos, join_pos)
        if guard_pos < problem_pos:
            return True

    return False


def _scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue

        # Check for bare `.translate(` or `.join(` without guard
        if (_RE_BARE_TRANSLATE.search(line) or _RE_BARE_JOIN.search(line)):
            # Look backward through the previous 3 lines for an if-guard
            # (accounting for indented code blocks)
            current_indent = len(line) - len(line.lstrip())
            has_guard_nearby = False
            
            for prev_offset in range(1, 4):  # Check up to 3 lines back
                if lineno - prev_offset < 1:
                    break
                prev_line = lines[lineno - prev_offset - 1]
                prev_indent = len(prev_line) - len(prev_line.lstrip())
                
                # If previous line has less indentation and has guard, it likely guards this line
                if prev_indent < current_indent and _RE_GUARD.search(prev_line):
                    has_guard_nearby = True
                    break
            
            if not has_guard_nearby and not _has_guard(line):
                snippet = line.strip()[:120]
                violations.append(f"{path}:{lineno}: unconditional_translate_or_join: {snippet}")

    return violations


def _iter_python_files(roots: Iterable[str]) -> Iterable[Path]:
    for root_str in roots:
        root = REPO_ROOT / root_str
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix == ".py":
                yield root
        else:
            for path in root.rglob("*.py"):
                if not path.name.endswith(EXEMPT_SUFFIX_FILE):
                    yield path


def main(argv: list[str]) -> int:
    roots = argv[1:] if len(argv) > 1 else list(DEFAULT_ROOTS)
    all_violations: list[str] = []

    for path in _iter_python_files(roots):
        violations = _scan_file(path)
        all_violations.extend(violations)

    if all_violations:
        for violation in sorted(all_violations):
            print(violation)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
