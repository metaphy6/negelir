#!/usr/bin/env python3
"""
`make up|down|restart|ai|server|infra` — service lifecycle.

All targets are thin `docker compose` wrappers. We use `compose_exec`
(execvp) so the user's TTY, signals, and exit code pass through
to docker compose without an extra Python layer.

Env-var flags:
    DETACH=1   → `make up` runs in background (`-d`)
"""

from __future__ import annotations

import os
import sys

from _common import compose_exec, compose_run, dispatch, info


def _detach() -> bool:
    return os.environ.get("DETACH", "").strip() not in ("", "0", "false", "False")


def cmd_up(_argv):
    if _detach():
        compose_exec("up", "--build", "-d")
    else:
        compose_exec("up", "--build")


def cmd_down(_argv):
    compose_exec("down")


def cmd_ai(_argv):
    compose_exec("up", "--build", "ai")


def cmd_server(_argv):
    compose_exec("up", "--build", "postgres", "redis", "server")


def cmd_infra(_argv):
    compose_exec("up", "-d", "postgres", "redis")


def cmd_restart(_argv):
    info("Restarting stack…")
    compose_run("down")
    compose_exec("up", "--build")


COMMANDS = {
    "up": cmd_up,
    "down": cmd_down,
    "restart": cmd_restart,
    "ai": cmd_ai,
    "server": cmd_server,
    "infra": cmd_infra,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="services.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
