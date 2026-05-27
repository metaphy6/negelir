#!/usr/bin/env python3
"""
no_pool_per_request.py -- §9.17.3 no-pool-per-request lint rule.

Scans Go source files under the configured roots and flags any call to
pgx.Connect( or redis.NewClient( made outside
server/internal/bootstrap/.

Rationale (§9.17.3): connection pools must be created ONCE at process start
inside server/internal/bootstrap/, not once per request or once per
handler initialisation.  Creating a new pool per-request exhausts file
descriptors, bypasses pool sizing limits, and defeats the §9.17.3 knobs.

Default scan roots:
  - server/cmd/api/
  - server/internal/   (bootstrap/ subtree is auto-excluded as the allowed origin)

Test files (*_test.go) are exempt — test helpers are allowed to create
isolated clients against miniredis/testcontainers.

Exit codes: 0 = clean, 1 = violations found, 2 = usage error.
Output: one line per violation, path:line: kind: snippet.

Stdlib-only (per AGENTS.md §5).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Default roots to scan (relative to repo root).
DEFAULT_ROOTS: tuple[str, ...] = (
    "server/cmd/api",
    "server/internal",
)

# The one path that IS allowed to create pools.
BOOTSTRAP_PREFIX = "server/internal/bootstrap"

EXEMPT_SUFFIX = "_test.go"
ALLOW_MARKER  = "no_pool_per_request: allow"

# Forbidden call patterns.
_RE_PGX_CONNECT    = re.compile(r"pgx\.Connect\(")
_RE_REDIS_NEWCLIENT = re.compile(r"redis\.NewClient\(")

PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("pgx.Connect",      _RE_PGX_CONNECT),
    ("redis.NewClient",  _RE_REDIS_NEWCLIENT),
)


def _is_bootstrap(path: Path) -> bool:
    """Return True when *path* lives inside the allowed bootstrap subtree."""
    try:
        rel = path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return str(rel).startswith(BOOTSTRAP_PREFIX)


def _scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    if _is_bootstrap(path):
        return violations
    if path.name.endswith(EXEMPT_SUFFIX):
        return violations
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        return violations
    for lineno, raw in enumerate(lines, 1):
        if ALLOW_MARKER in raw:
            continue
        for kind, pattern in PATTERNS:
            if pattern.search(raw):
                snippet = raw.strip()[:120]
                violations.append(f"{path}:{lineno}: {kind}: {snippet}")
                break  # one violation per line
    return violations


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    roots: list[Path]
    if argv:
        roots = [Path(a) if Path(a).is_absolute() else REPO_ROOT / a for a in argv]
    else:
        roots = [REPO_ROOT / r for r in DEFAULT_ROOTS]

    violations: list[str] = []
    for root in roots:
        if not root.exists():
            print(f"warning: root {root} does not exist", file=sys.stderr)
            continue
        for go_file in sorted(root.rglob("*.go")):
            violations.extend(_scan_file(go_file))

    if violations:
        for v in violations:
            print(v)
        print(
            f"\nno_pool_per_request: {len(violations)} violation(s) found. "
            "Pool creation must live in server/internal/bootstrap/.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
