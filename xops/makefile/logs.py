#!/usr/bin/env python3
"""`make logs|logs-ai|logs-server` — tail container logs."""

from __future__ import annotations

import sys

from _common import compose_exec, dispatch


def cmd_logs(_argv):        compose_exec("logs", "-f")
def cmd_logs_ai(_argv):     compose_exec("logs", "-f", "ai")
def cmd_logs_server(_argv): compose_exec("logs", "-f", "server")


COMMANDS = {
    "logs": cmd_logs,
    "logs-ai": cmd_logs_ai,
    "logs-server": cmd_logs_server,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="logs.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
