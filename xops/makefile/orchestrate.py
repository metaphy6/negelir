#!/usr/bin/env python3
"""`make orchestrate.*` — ROADMAP phase orchestration dispatcher.

Thin wrapper around `xops.orchestrator.cli`. Make targets stay one-line per
target; the heavy lifting is in the Python package.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err  # noqa: E402
from xops.orchestrator import cli as orch_cli  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _filter_args() -> List[str]:
    args: List[str] = []
    inc = _env("INCLUDE")
    exc = _env("EXCLUDE")
    if inc:
        args += ["--include", inc]
    if exc:
        args += ["--exclude", exc]
    if _env("INCLUDE_BRANCHES") in ("1", "true", "yes"):
        args.append("--include-branches")
    if _env("INCLUDE_COMPLETE") in ("1", "true", "yes"):
        args.append("--include-complete")
    return args


def _maybe_json() -> List[str]:
    return ["--json"] if _env("JSON") in ("1", "true", "yes") else []


def cmd_list(_argv: List[str]) -> int:
    extra = ["--leaves-only"] if _env("LEAVES") in ("1", "true", "yes") else []
    return orch_cli.main([*_maybe_json(), "list", *extra])


def cmd_plan(_argv: List[str]) -> int:
    return orch_cli.main([*_maybe_json(), "plan", *_filter_args()])


def cmd_next(_argv: List[str]) -> int:
    return orch_cli.main([*_maybe_json(), "next", *_filter_args()])


def cmd_slice(_argv: List[str]) -> int:
    phase = _env("PHASE")
    out = _env("OUT")
    if not phase:
        err("usage: make orchestrate.slice PHASE=<id> [OUT=path]")
        return 64
    args = [*_maybe_json(), "slice", phase]
    if out:
        args += ["--out", out]
    return orch_cli.main(args)


def cmd_claim(_argv: List[str]) -> int:
    phase = _env("PHASE")
    if not phase:
        err("usage: make orchestrate.claim PHASE=<id> [CLAIMER=<id>]")
        return 64
    args = [*_maybe_json(), "claim", phase]
    claimer = _env("CLAIMER")
    if claimer:
        args += ["--claimer", claimer]
    return orch_cli.main(args)


def cmd_release(_argv: List[str]) -> int:
    phase = _env("PHASE")
    if not phase:
        err("usage: make orchestrate.release PHASE=<id> [FORCE=1]")
        return 64
    args = [*_maybe_json(), "release", phase]
    if _env("FORCE") in ("1", "true", "yes"):
        args.append("--force")
    return orch_cli.main(args)


def cmd_locks(_argv: List[str]) -> int:
    return orch_cli.main([*_maybe_json(), "locks"])


def cmd_state(_argv: List[str]) -> int:
    args = [*_maybe_json(), "state"]
    phase = _env("PHASE")
    if phase:
        args.append(phase)
    return orch_cli.main(args)


def cmd_advance(_argv: List[str]) -> int:
    phase = _env("PHASE")
    if not phase:
        err("usage: make orchestrate.advance PHASE=<id> "
            "[STATUS=...] [ROLE=...] [OUTCOME=...] [MODEL=...] [NOTES=...]")
        return 64
    args = [*_maybe_json(), "advance", phase]
    for env_key, flag in (
        ("STATUS", "--status"),
        ("ROLE", "--role"),
        ("OUTCOME", "--outcome"),
        ("MODEL", "--model"),
        ("NOTES", "--notes"),
        ("DIFF_SUMMARY", "--diff-summary"),
        ("LAST_ERROR", "--last-error"),
    ):
        v = _env(env_key)
        if v:
            args += [flag, v]
    return orch_cli.main(args)


def cmd_unlock(_argv: List[str]) -> int:
    """Operator-only: forcibly clear a stale lock."""
    phase = _env("PHASE")
    if not phase:
        err("usage: make orchestrate.unlock PHASE=<id>")
        return 64
    return orch_cli.main([*_maybe_json(), "release", phase, "--force"])


COMMANDS = {
    "list": cmd_list,
    "plan": cmd_plan,
    "next": cmd_next,
    "slice": cmd_slice,
    "claim": cmd_claim,
    "release": cmd_release,
    "locks": cmd_locks,
    "state": cmd_state,
    "advance": cmd_advance,
    "unlock": cmd_unlock,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="orchestrate.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
