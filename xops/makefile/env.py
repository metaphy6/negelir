#!/usr/bin/env python3
"""`make env` — bootstrap the .env file from .env.example."""

from __future__ import annotations

import shutil
import sys

from _common import REPO_ROOT, dispatch, info, ok


def cmd_env(_argv):
    src = REPO_ROOT / ".env.example"
    dst = REPO_ROOT / ".env"
    if dst.exists():
        info(f".env exists ({dst})")
        return 0
    if not src.exists():
        print(f"❌ Missing template: {src}", file=sys.stderr)
        return 1
    shutil.copyfile(src, dst)
    ok(f"Created .env from .env.example ({dst})")
    return 0


COMMANDS = {"env": cmd_env}


def main(argv=None):
    return dispatch(argv if argv is not None else sys.argv[1:], COMMANDS, script_name="env.py")


if __name__ == "__main__":
    raise SystemExit(main())
