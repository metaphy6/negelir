#!/usr/bin/env python3
"""git_guard — pre-commit / pre-push scope check for agent CI runs.

Used by `.github/workflows/orchestrate-roadmap.yml` to refuse commits
that violate the constraints in
`.github/instructions/ci-pipeline.instructions.md`. Two modes:

    git_guard.py --check-staged
        Inspect `git diff --cached --name-only` and refuse if any
        staged path is on the forbidden list, or if a code change
        was staged without a paired tracker row / version bump.

    git_guard.py --check-commit <REF>
        Inspect a single committed ref (used by the auto-merge job
        to vet what landed). Same logic, but reads
        `git show --name-only <REF>` instead of the index.

Exit codes:
    0   clean
    2   scope violation (printed reason on stderr)
    3   missing paired tracker row / version bump
    4   forbidden-message pattern (e.g. mentions `--no-verify`)

This script must be stdlib-only — it runs on the bare Ubuntu image
before any `pip install`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Paths the agent may NEVER edit in CI, even on agent/** branches.
# Mirrors AGENTS.md §2 forbidden-edits + ci-pipeline.instructions.md §9.
FORBIDDEN_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    ".github/instructions/",
    ".github/prompts/",
    ".github/chatmodes/",
    ".github/workflows/",
    ".vscode/mcp.json",
    "xops/versioning/chart.json",
    "docs/tracking/phases.csv",
    "server/internal/auth/",
    "server/internal/payment/",
)

# Paths that hint a code change is occurring (so a paired tracker row
# + version bump must also be present in the same diff).
CODE_GLOBS = (
    re.compile(r"^ai/.*\.py$"),
    re.compile(r"^server/.*\.go$"),
    re.compile(r"^xops/.*\.py$"),
)

TRACKER_PATH = "docs/tracking/phases.csv"
VERSION_PATH = "xops/versioning/chart.json"

WIP_PREFIX = "WIP:"
BANNED_MSG_PATTERNS = (
    re.compile(r"--no-verify", re.IGNORECASE),
    re.compile(r"skip\s*ci", re.IGNORECASE),
)


def _run(*args: str) -> str:
    return subprocess.run(
        list(args), check=True, capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout


def _staged_paths() -> list[str]:
    out = _run("git", "diff", "--cached", "--name-only")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_paths(ref: str) -> list[str]:
    out = _run("git", "show", "--name-only", "--pretty=format:", ref)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _commit_message(ref: str) -> str:
    return _run("git", "log", "-1", "--pretty=%B", ref)


def _is_forbidden(path: str) -> str | None:
    """Return the matching forbidden prefix, or None."""
    for fp in FORBIDDEN_PATHS:
        if fp.endswith("/"):
            if path.startswith(fp):
                return fp
        elif path == fp:
            return fp
    return None


def _is_code_change(path: str) -> bool:
    return any(rx.match(path) for rx in CODE_GLOBS)


def _check_paths(paths: list[str], *, allow_governance: bool) -> int:
    if not paths:
        print("git_guard: no changed paths", file=sys.stderr)
        return 0

    # 1) Forbidden paths.
    if not allow_governance:
        violations = [
            (p, fp) for p in paths if (fp := _is_forbidden(p)) is not None
        ]
        if violations:
            print("git_guard: forbidden-path edits detected:", file=sys.stderr)
            for path, fp in violations:
                print(f"  - {path}  (matched forbidden prefix: {fp})",
                      file=sys.stderr)
            print(
                "  set ALLOW_GOVERNANCE_EDIT=1 only when a human explicitly "
                "named these files in the dispatch payload.",
                file=sys.stderr,
            )
            return 2

    # 2) Paired tracker row + version bump when code changed.
    code_changes = [p for p in paths if _is_code_change(p)]
    if code_changes:
        if TRACKER_PATH not in paths:
            print(
                f"git_guard: code changed but {TRACKER_PATH} was not updated "
                "in the same commit. AGENTS.md §3.3 requires the tracker row "
                "to land in the same commit as the work. Run `make track.add`.",
                file=sys.stderr,
            )
            print("  code paths:", file=sys.stderr)
            for p in code_changes:
                print(f"    - {p}", file=sys.stderr)
            return 3
        if VERSION_PATH not in paths:
            print(
                f"git_guard: code changed but {VERSION_PATH} was not updated. "
                "AGENTS.md §6.1 requires `make version.bump COMPONENT=… "
                "LEVEL=… NOTE=\"…\"` in the same commit.",
                file=sys.stderr,
            )
            return 3

    return 0


def _check_message(msg: str, *, allow_wip: bool) -> int:
    for rx in BANNED_MSG_PATTERNS:
        if rx.search(msg):
            print(
                f"git_guard: commit message contains banned pattern "
                f"({rx.pattern!r}). CI gates must not be bypassed.",
                file=sys.stderr,
            )
            return 4
    if not allow_wip and msg.lstrip().startswith(WIP_PREFIX):
        print(
            "git_guard: WIP commit on this ref is not allowed. "
            "WIP commits are only valid mid-run on the agent branch; "
            "this guard ran in --check-commit mode against a finalized ref.",
            file=sys.stderr,
        )
        return 4
    return 0


def cmd_check_staged(_args: argparse.Namespace) -> int:
    allow_governance = os.environ.get("ALLOW_GOVERNANCE_EDIT") == "1"
    rc = _check_paths(_staged_paths(), allow_governance=allow_governance)
    if rc != 0:
        return rc
    print("git_guard: staged diff clean", file=sys.stderr)
    return 0


def cmd_check_commit(args: argparse.Namespace) -> int:
    allow_governance = os.environ.get("ALLOW_GOVERNANCE_EDIT") == "1"
    paths = _commit_paths(args.ref)
    rc = _check_paths(paths, allow_governance=allow_governance)
    if rc != 0:
        return rc
    msg = _commit_message(args.ref)
    rc = _check_message(msg, allow_wip=args.allow_wip)
    if rc != 0:
        return rc
    print(f"git_guard: commit {args.ref} clean", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="git_guard")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check-staged", help="inspect the current staged diff")
    s.set_defaults(func=cmd_check_staged)

    s = sub.add_parser("check-commit", help="inspect one finalized commit")
    s.add_argument("ref", help="commit ref (sha or symbolic)")
    s.add_argument("--allow-wip", action="store_true",
                   help="permit WIP-prefixed messages (mid-run only)")
    s.set_defaults(func=cmd_check_commit)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        print(f"git_guard: git command failed: {exc.stderr.strip()}",
              file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
