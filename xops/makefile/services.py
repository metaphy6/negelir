#!/usr/bin/env python3
"""
`make build|up|up-detached|down|restart|ai|server|infra` — service lifecycle.

All targets are thin `docker compose` wrappers. We use `compose_exec`
(execvp) so the user's TTY, signals, and exit code pass through
to docker compose without an extra Python layer.
"""

from __future__ import annotations

import sys

from _common import compose_exec, compose_run, dispatch, info


def cmd_build(_argv):       compose_exec("build")
def cmd_up(_argv):          compose_exec("up", "--build")
def cmd_up_detached(_argv): compose_exec("up", "--build", "-d")
def cmd_down(_argv):        compose_exec("down")
def cmd_ai(_argv):          compose_exec("up", "--build", "ai")
def cmd_server(_argv):      compose_exec("up", "--build", "postgres", "redis", "server")
def cmd_infra(_argv):       compose_exec("up", "-d", "postgres", "redis")


def cmd_restart(_argv):
    info("Restarting stack…")
    compose_run("down")
    compose_exec("up", "--build")


COMMANDS = {
    "build": cmd_build,
    "up": cmd_up,
    "up-detached": cmd_up_detached,
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
