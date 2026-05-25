#!/usr/bin/env python3
"""`make version.*` — versioning chart dispatcher.

Thin wrapper around ``xops.versioning.version`` so the Makefile stays
one-line per target.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, err  # noqa: E402
from xops.versioning import version as v  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def cmd_show(_argv: List[str]) -> int:
    import argparse

    parser = v.build_parser()
    return v.main(["show", "--changelog", _env("CHANGELOG", "0") or "0"])


def cmd_bump(_argv: List[str]) -> int:
    component = _env("COMPONENT")
    level = _env("LEVEL")
    note = _env("NOTE")
    if not component or not level:
        err(
            "usage: make version.bump COMPONENT=<key> LEVEL=<major|minor|patch> "
            "[NOTE=\"...\"]"
        )
        return 64
    args = ["bump", "--component", component, "--level", level]
    if note:
        args += ["--note", note]
    return v.main(args)


def cmd_validate(_argv: List[str]) -> int:
    return v.main(["validate"])


def cmd_compatibility_check(_argv: List[str]) -> int:
    return v.main(["compatibility-check"])


COMMANDS = {
    "show": cmd_show,
    "bump": cmd_bump,
    "validate": cmd_validate,
    "compatibility-check": cmd_compatibility_check,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="version.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
