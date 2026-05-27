#!/usr/bin/env python3
"""
no_init_alloc.py — §9.17.1 boot-time allocation guard.

Rejects two patterns in Go source files outside _test.go:

  1. make([]T, N) where N > 1<<20 (1 MiB elements)
  2. bytes.Repeat(x, N) where N > 1<<20

These indicate init-time (or large static) allocations that violate the
§9.17.1 contract: heap baseline at first request must be < 32 MiB on a
no-traffic pod.

Only scans Go source files under server/ that are NOT _test.go.

Exit code: 0 = clean, 1 = violations found, 2 = usage error.
Output: one line per violation, ``path:line: kind: snippet``.

Stdlib-only (per AGENTS.md §5: cross-platform, no third-party deps).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS: tuple[str, ...] = ("server",)

# Exempt test files.
EXEMPT_SUFFIX = "_test.go"

# Pattern 1: make([]T, N) with N as a literal > 1<<20
# We capture the literal and evaluate it.
_MAKE_RE = re.compile(
    r"\bmake\s*\(\s*\[\s*\]\s*\w[\w.]*\s*,\s*([0-9_]+(?:\s*<<\s*[0-9]+)?)\s*\)",
    re.ASCII,
)

# Pattern 2: bytes.Repeat(expr, N) with N as a literal > 1<<20
_REPEAT_RE = re.compile(
    r"\bbytes\.Repeat\s*\([^,]+,\s*([0-9_]+(?:\s*<<\s*[0-9]+)?)\s*\)",
    re.ASCII,
)

_THRESHOLD = 1 << 20  # 1 MiB


def _eval_literal(s: str) -> int | None:
    """Evaluate an integer literal (decimal or bit-shift) safely."""
    s = s.replace("_", "")
    if "<<" in s:
        parts = s.split("<<", 1)
        try:
            return int(parts[0].strip()) << int(parts[1].strip())
        except (ValueError, OverflowError):
            return None
    try:
        return int(s)
    except ValueError:
        return None


def _scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations
    for lineno, line in enumerate(lines, start=1):
        for pat, kind in ((_MAKE_RE, "large_make"), (_REPEAT_RE, "large_bytes_repeat")):
            for m in pat.finditer(line):
                val = _eval_literal(m.group(1))
                if val is not None and val > _THRESHOLD:
                    snippet = line.strip()[:120]
                    violations.append(
                        f"{path}:{lineno}: {kind}: {snippet}"
                    )
    return violations


def main(argv: list[str]) -> int:
    roots = argv[1:] if len(argv) > 1 else [str(REPO_ROOT / r) for r in SCAN_ROOTS]
    all_violations: list[str] = []
    for root_s in roots:
        root = Path(root_s)
        for go_file in sorted(root.rglob("*.go")):
            if go_file.name.endswith(EXEMPT_SUFFIX):
                continue
            all_violations.extend(_scan_file(go_file))
    for v in all_violations:
        print(v)
    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
