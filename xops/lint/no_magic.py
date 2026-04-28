#!/usr/bin/env python3
"""
no_magic.py — Phase 1.4 hardcode audit.

Forbids in production code (anything under ``ai/`` outside ``ai/tests/``):

    1. ``time.sleep(<int|float literal>)``     — use config-driven timeouts
    2. ``localhost:<port>`` in string literals — use env-driven host/port
    3. ``requests.{get,post,...}("http(s)://...")`` — base URL must be config

Allowed locations:
    * ``ai/tests/**``               — tests can do whatever
    * ``ai/common/config.py``       — config defaults are by construction
    * ``ai/common/defaults.yaml``   — same
    * Any path matching ``# no_magic: allow`` on the offending line

Exit code 0 = clean, 1 = violations found, 2 = bad CLI invocation.
The output is one line per violation, ``path:line: kind: snippet``.

Stdlib-only on purpose (per AGENTS.md §5: cross-platform, no third-party deps).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_ROOTS: tuple[str, ...] = ("ai",)

# Files / globs always exempt.
ALLOW_PATHS: tuple[str, ...] = (
    "ai/common/config.py",
    "ai/common/defaults.yaml",
)
# Tests are exempt anywhere they live under `ai/`. We match by path
# segment rather than a hard-coded prefix because Phase 3 (SDK) and
# Phase 4 (worker agents) put their tests under sibling `tests/`
# directories (`ai/swarm/sdk/tests/`, `ai/swarm/agents/tests/`,
# `ai/swarm/source_watcher/tests/`), and the lint must keep up
# without a manual edit each time a new agent package lands.
ALLOW_DIRS: tuple[str, ...] = (
    "ai/tests/",
)
# Substring markers used by `_is_exempt` to catch test trees that are
# not at the top level (e.g. `ai/swarm/agents/tests/...`). Anything
# whose POSIX path contains `/tests/` is exempt.
ALLOW_PATH_FRAGMENTS: tuple[str, ...] = (
    "/tests/",
)

# Per-line opt-out marker.
ALLOW_MARKER = "no_magic: allow"

# ── Patterns ─────────────────────────────────────────────────────────────

# time.sleep(<numeric literal>) — flag both int and float, but skip
# `time.sleep(self.foo)`, `time.sleep(cfg.x)`, `time.sleep(SOME_CONST)`.
_RE_TIME_SLEEP = re.compile(r"\btime\.sleep\(\s*[+-]?\d+(?:\.\d+)?\s*\)")

# `localhost:<port>` substring in a string literal.
_RE_LOCALHOST_PORT = re.compile(r"localhost:\d+")

# requests.METHOD("http(s)://...") with a URL literal as the first arg.
_RE_REQUESTS_LITERAL = re.compile(
    r"\brequests\.(?:get|post|put|patch|delete|head|options|request)\s*\(\s*[\"']https?://"
)


PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("time.sleep(<literal>)", _RE_TIME_SLEEP),
    ("localhost:<port>", _RE_LOCALHOST_PORT),
    ("requests.<method>(literal URL)", _RE_REQUESTS_LITERAL),
)


# ── Walker ───────────────────────────────────────────────────────────────


def _is_exempt(rel: str) -> bool:
    if rel in ALLOW_PATHS:
        return True
    if any(rel.startswith(d) for d in ALLOW_DIRS):
        return True
    return any(frag in rel for frag in ALLOW_PATH_FRAGMENTS)


def _iter_python_files(roots: Iterable[str]) -> Iterable[Path]:
    for root in roots:
        base = (REPO_ROOT / root).resolve()
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            yield path


def scan(roots: Iterable[str] = DEFAULT_ROOTS) -> list[str]:
    """Return a list of human-readable violation strings."""
    violations: list[str] = []
    for path in _iter_python_files(roots):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if _is_exempt(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARKER in line:
                continue
            for kind, pattern in PATTERNS:
                m = pattern.search(line)
                if not m:
                    continue
                snippet = line.strip()
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."
                violations.append(f"{rel}:{lineno}: {kind}: {snippet}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help="Root directories to scan (default: %(default)s)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress 'clean' message on success",
    )
    args = parser.parse_args(argv)

    violations = scan(args.roots)
    if violations:
        print("❌ no_magic: violations found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            f"\nTotal: {len(violations)} violation(s). Add `# {ALLOW_MARKER}` "
            "to the offending line to acknowledge, or move the value into config.",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print(f"✅ no_magic: clean across {', '.join(args.roots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
