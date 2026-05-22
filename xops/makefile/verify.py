#!/usr/bin/env python3
"""`make verify.*` — repository verification helpers."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
XOPS_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(XOPS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from _common import dispatch  # noqa: E402


def cmd_dlq_replay_policy(_argv: list[str]) -> int:
    from xops.maint.verify_dlq_replay_policy import main as verify_main

    return int(verify_main([]))


COMMANDS = {
    "dlq-replay-policy": cmd_dlq_replay_policy,
}


def main(argv: list[str] | None = None) -> int:
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="verify.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
