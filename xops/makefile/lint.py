#!/usr/bin/env python3
"""`make lint` — Phase 1.4 hardcode audit dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure xops/ is on sys.path for sibling import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import dispatch  # noqa: E402
from lint.no_magic import main as no_magic_main  # noqa: E402


def cmd_lint(argv):
    return no_magic_main(list(argv))


COMMANDS = {
    "lint": cmd_lint,
    "no-magic": cmd_lint,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="lint.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
