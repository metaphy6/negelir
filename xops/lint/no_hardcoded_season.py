#!/usr/bin/env python3
"""
no_hardcoded_season.py — Phase 22.6 CURRENT_SEASON migration audit.

Forbids in production code (anything outside ``common/config/``):

    1. Bare ``CURRENT_SEASON`` references (attribute access)
    2. String literals like ``"CURRENT_SEASON"`` used as config keys
    3. Imports like ``from common.constants import CURRENT_SEASON``

The CURRENT_SEASON constant has been removed; all code must use
``cfg.default_season`` (from Config in ``common/config/ai_pipeline.py``)
or ``current_season()`` (from ``common/season.py``) instead.

Allowed locations:
    * ``common/config/**``           — config layer owns the defaults
    * ``common/constants.py``        — the file itself (already migrated)
    * ``common/season.py``           — the function definition
    * ``**/tests/**``                — tests can reference for validation
    * Any path matching ``# no_hardcoded_season: allow`` on the offending line

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

DEFAULT_ROOTS: tuple[str, ...] = ("common", "ai", "server", "swarm", "datasource", "enrichment", "migration", "nlp", "orchestrator", "pipeline", "proofreader", "qid", "scraper", "tqu", "trc", "backtest")

# Files / globs always exempt.
ALLOW_PATHS: tuple[str, ...] = (
    "common/config/ai_pipeline.py",
    "common/config/defaults.yaml",
    "common/constants.py",  # Already migrated
    "common/season.py",     # Function definition
)

# Tests are exempt anywhere they live.
ALLOW_DIRS: tuple[str, ...] = ()

# Substring markers for test trees.
ALLOW_PATH_FRAGMENTS: tuple[str, ...] = (
    "/tests/",
)

# Per-line opt-out marker.
ALLOW_MARKER = "no_hardcoded_season: allow"

# ── Patterns ─────────────────────────────────────────────────────────────

# Bare CURRENT_SEASON reference (not in a comment or docstring)
# This catches: CURRENT_SEASON, constants.CURRENT_SEASON, etc.
# But avoids: current_season (the function), CURRENT_SEASON_X, _CURRENT_SEASON
_RE_CURRENT_SEASON_BARE = re.compile(
    r'\bCURRENT_SEASON\b'
)

# Import of CURRENT_SEASON from constants
_RE_IMPORT_CURRENT_SEASON = re.compile(
    r'from\s+\S*constants\s+import\s+.*\bCURRENT_SEASON\b'
)

# String literal reference to CURRENT_SEASON as a config key
_RE_STRING_LITERAL_CURRENT_SEASON = re.compile(
    r'["\']CURRENT_SEASON["\']'
)

PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("import CURRENT_SEASON from constants", _RE_IMPORT_CURRENT_SEASON),
    ("bare CURRENT_SEASON reference", _RE_CURRENT_SEASON_BARE),
    ("string literal 'CURRENT_SEASON'", _RE_STRING_LITERAL_CURRENT_SEASON),
)


# ── Walker ───────────────────────────────────────────────────────────────


def _is_exempt(rel: str) -> bool:
    if rel in ALLOW_PATHS:
        return True
    if any(rel.startswith(d) for d in ALLOW_DIRS):
        return True
    if any(frag in rel for frag in ALLOW_PATH_FRAGMENTS):
        return True
    return False


def _is_comment_or_docstring_line(line: str) -> bool:
    """Check if the line is likely a comment, docstring, or URL reference."""
    stripped = line.lstrip()
    # Comment
    if stripped.startswith("#"):
        return True
    # Docstring/comment continuation
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return True
    if "http://" in line or "https://" in line:
        return True
    return False


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
            if _is_comment_or_docstring_line(line):
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
        print("❌ no_hardcoded_season: violations found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            f"\nTotal: {len(violations)} violation(s). Use cfg.default_season or "
            "current_season() instead, or add `# no_hardcoded_season: allow` to acknowledge.",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print(f"✅ no_hardcoded_season: clean across {', '.join(args.roots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
