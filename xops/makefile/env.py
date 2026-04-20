#!/usr/bin/env python3
"""`make env` — bootstrap xops/env/.env from xops/env/.env.example."""

from __future__ import annotations

import shutil
import sys

from _common import ENV_EXAMPLE, ENV_FILE, dispatch, info, ok


def cmd_env(_argv):
    src = ENV_EXAMPLE
    dst = ENV_FILE
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        info(f"env file exists ({dst.relative_to(src.parent.parent.parent)})")
        return 0
    if not src.exists():
        print(f"❌ Missing template: {src}", file=sys.stderr)
        return 1
    shutil.copyfile(src, dst)
    ok(f"Created {dst.relative_to(src.parent.parent.parent)} from {src.relative_to(src.parent.parent.parent)}")
    return 0


COMMANDS = {"env": cmd_env}


def main(argv=None):
    return dispatch(argv if argv is not None else sys.argv[1:], COMMANDS, script_name="env.py")


if __name__ == "__main__":
    raise SystemExit(main())
