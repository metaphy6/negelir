#!/usr/bin/env python3
"""
`make logs` — tail container logs.

Env-var:
    SVC=ai|server|postgres|… → tail one service (default: all services)
"""

from __future__ import annotations

import os
import sys

from _common import compose_exec, dispatch


def cmd_logs(_argv):
    svc = os.environ.get("SVC", "").strip()
    args = ["logs", "-f"]
    if svc:
        args.append(svc)
    compose_exec(*args)


COMMANDS = {
    "logs": cmd_logs,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="logs.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
