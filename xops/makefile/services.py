#!/usr/bin/env python3
"""
`make up|down|restart|ai|server|infra` — service lifecycle.

All targets are thin `docker compose` wrappers. We use `compose_exec`
(execvp) so the user's TTY, signals, and exit code pass through
to docker compose without an extra Python layer.

Env-var flags:
    DETACH=1            → `make up` runs in background (`-d`)
    PROFILES=core,...   → Selective profile activation (default: core,server,swarm)
                          See COMPONENT_LAYOUT.md §4 for profile documentation.
"""

from __future__ import annotations

import os
import sys

from _common import compose_exec, compose_run, dispatch, info, warn


def _detach() -> bool:
    return os.environ.get("DETACH", "").strip() not in ("", "0", "false", "False")


def _get_profiles() -> list[str]:
    """Get profiles from PROFILES env var, default to core,server,swarm."""
    profiles_str = os.environ.get("PROFILES", "core,server,swarm").strip()
    if not profiles_str:
        profiles_str = "core,server,swarm"
    return [f"--profile={p.strip()}" for p in profiles_str.split(",") if p.strip()]


def cmd_up(_argv):
    """Start services with PROFILES (default: core,server,swarm)."""
    profiles = _get_profiles()
    if _detach():
        compose_exec("up", "--build", "-d", *profiles)
    else:
        compose_exec("up", "--build", *profiles)


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
    profiles = _get_profiles()
    compose_exec("up", "--build", *profiles)


def cmd_up_dev(_argv):
    """DEPRECATED: Use 'make up PROFILES=...' instead."""
    warn("make up-dev is deprecated as of Phase 18.4")
    warn("Use: make up PROFILES=core,mock,datasource")
    sys.exit(1)


def cmd_up_mock(_argv):
    """DEPRECATED: Use 'make up PROFILES=core,mock' instead."""
    warn("make up-mock is deprecated as of Phase 18.4")
    warn("Use: make up PROFILES=core,mock")
    sys.exit(1)


COMMANDS = {
    "up": cmd_up,
    "down": cmd_down,
    "restart": cmd_restart,
    "ai": cmd_ai,
    "server": cmd_server,
    "infra": cmd_infra,
    "up-dev": cmd_up_dev,
    "up-mock": cmd_up_mock,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="services.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
